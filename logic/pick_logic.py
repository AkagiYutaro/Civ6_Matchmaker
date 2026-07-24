import time
import asyncio
import random
import datetime
import logging
import discord
from logic.banpick_logic import format_leader_list

logger = logging.getLogger('discord.pick_logic')

def get_pick_timer(sheet_manager):
    """スプレッドシートからピック制限時間を取得する（秒）。取得できなければ180秒(3分)とする"""
    try:
        master = sheet_manager.get_master_config()
        for row in master:
            if str(row.get("FLG名", "")) == "ピック時間" or str(row.get("カテゴリ", "")) == "ピック時間":
                val = str(row.get("現在の配点", "")).strip()
                if val.isdigit():
                    return int(val)
    except Exception as e:
        logger.warning(f"ピック時間の取得に失敗しました。デフォルトの180秒を使用します。: {e}")
    return 180

class PickPhaseManager:
    def __init__(self, interaction, host, team_a, team_b, survivors, all_leaders, banned_global, banned_a, banned_b, sheet_manager):
        self.original_interaction = interaction
        self.host = host
        self.team_a = team_a
        self.team_b = team_b
        self.survivors = survivors
        self.all_leaders = all_leaders
        
        self.banned_global = banned_global
        self.banned_a = banned_a
        self.banned_b = banned_b
        self.sheet_manager = sheet_manager
        
        # {user_id: {"leader": uid, "confirmed": bool}}
        self.picks = {} 
        self.is_completed = False
        
        self.duration = get_pick_timer(sheet_manager)
        self.end_time = int(time.time()) + self.duration
        self.timeout_task = None
        self.entry_message = None

    def start_timer(self, entry_message):
        """UI側で送信されたメッセージを受け取り、タイマーを開始する"""
        self.entry_message = entry_message
        self.timeout_task = asyncio.create_task(self.timer_loop())

    async def timer_loop(self):
        while self.end_time > time.time():
            if self.is_completed:
                return
            await asyncio.sleep(1)
            
        if not self.is_completed:
            self.force_confirm_unpicked()
            await self.finish_pick()

    def force_confirm_unpicked(self):
        """時間切れになった場合、未確定の人にランダムで残りの指導者を割り当てる"""
        all_players = self.team_a + self.team_b
        used_uids = [d["leader"] for d in self.picks.values() if d.get("confirmed")]
        available = [L['uid'] for L in self.survivors if L['uid'] not in used_uids]
        
        for uid in all_players:
            data = self.picks.get(uid, {"leader": None, "confirmed": False})
            if not data.get("confirmed"):
                temp = data.get("leader")
                if temp and temp in available:
                    final_uid = temp
                else:
                    final_uid = random.choice(available)
                
                if final_uid in available:
                    available.remove(final_uid)
                self.picks[uid] = {"leader": final_uid, "confirmed": True}

    async def check_all_completed(self):
        all_players = self.team_a + self.team_b
        confirmed_count = sum(1 for uid in all_players if self.picks.get(uid, {}).get("confirmed"))
        if confirmed_count >= len(all_players):
            self.is_completed = True
            if self.timeout_task:
                self.timeout_task.cancel()
            await self.finish_pick()

    async def finish_pick(self):
        """全員完了時、または時間切れ時に最終結果を表示し、ログを記録する"""
        if self.entry_message:
            try:
                await self.entry_message.edit(content="✅ **全プレイヤーのピックが完了しました！**", view=None)
            except: pass
            
        embed = discord.Embed(title="BAN / PICK 結果", color=discord.Color.gold())
        
        # 1. メインBAN
        global_str = format_leader_list(self.banned_global, self.all_leaders)
        embed.add_field(name="🌐 メインBAN", value=global_str, inline=False)
        
        # 2. チームBAN
        ban_a_str = format_leader_list(self.banned_a, self.all_leaders)
        ban_b_str = format_leader_list(self.banned_b, self.all_leaders)
        embed.add_field(name="🚫 BAN", value=f"**【🔵 チームAのBAN】**\n{ban_a_str}\n\n**【🔴 チームBのBAN】**\n{ban_b_str}", inline=False)
        
        # 3. チームPICK (画面表示の作成と、ログ記録用のデータ準備)
        match_id = f"MATCH-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        details_to_record = []
        
        def get_pick_str(team_ids, team_name):
            lines = []
            for uid in team_ids:
                l_id = self.picks.get(uid, {}).get("leader")
                leader = next((l for l in self.all_leaders if l['uid'] == l_id), None)
                if leader:
                    emoji = leader.get('emoji_text', '')
                    name = leader['clean_name']
                    lines.append(f"<@{uid}> : {emoji} **{name}**")
                    
                    # 💡 スプレッドシート記録用データの作成
                    # IDからサーバー内のメンバーを取得し、表示名(名前)を取得する
                    member = self.original_interaction.guild.get_member(uid)
                    player_name = member.display_name if member else f"ID: {uid}"
                    details_to_record.append([match_id, timestamp, str(uid), player_name, team_name, name, ""])
                else:
                    lines.append(f"<@{uid}> : ランダム(エラー)")
            return "\n".join(lines) if lines else "なし"
            
        pick_a_str = get_pick_str(self.team_a, "チームA")
        pick_b_str = get_pick_str(self.team_b, "チームB")
        
        embed.add_field(name="✅ PICK", value=f"**【🔵 チームAのPICK】**\n{pick_a_str}\n\n**【🔴 チームBのPICK】**\n{pick_b_str}", inline=False)
        
        await self.original_interaction.channel.send(embed=embed)
        
        # 💡 非同期でスプレッドシートに詳細ログを書き込む
        if details_to_record and self.sheet_manager:
            self.original_interaction.client.loop.create_task(
                asyncio.to_thread(self.sheet_manager.record_match_details, details_to_record)
            )