import time
import asyncio
import random
import datetime
import logging
import discord
from logic.banpick_logic import format_leader_list

logger = logging.getLogger('discord.pick_logic')

# 日本時間を指定
JST = datetime.timezone(datetime.timedelta(hours=9))

def get_pick_timer(sheet_manager):
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
        
        self.picks = {} 
        self.is_completed = False
        
        self.duration = get_pick_timer(sheet_manager)
        self.end_time = int(time.time()) + self.duration
        self.timeout_task = None
        self.entry_message = None

    def start_timer(self, entry_message):
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
        # 💡 修正: 完了時は黄色(Yellow)に変更し、全ての情報を美しく2列に整列させる
        embed = discord.Embed(title="投票結果", color=discord.Color.yellow())
        
        # 1. メインBAN (横並びなし)
        global_str = format_leader_list(self.banned_global, self.all_leaders)
        embed.add_field(name="🌐 メインBAN", value=global_str, inline=False)
        
        # 2. チームBAN (2列で横並び)
        ban_a_str = format_leader_list(self.banned_a, self.all_leaders)
        ban_b_str = format_leader_list(self.banned_b, self.all_leaders)
        embed.add_field(name="🔵 チームAのBAN", value=ban_a_str, inline=True)
        embed.add_field(name="🔴 チームBのBAN", value=ban_b_str, inline=True)
        
        # 見栄えを良くするための空白の区切り線
        embed.add_field(name="\u200B", value="\u200B", inline=False)
        
        now_jst = datetime.datetime.now(JST)
        match_id = f"MATCH-{now_jst.strftime('%Y%m%d-%H%M%S')}"
        timestamp = now_jst.strftime("%Y/%m/%d %H:%M:%S")
        
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
                    
                    member = self.original_interaction.guild.get_member(uid)
                    player_name = member.display_name if member else f"ID: {uid}"
                    details_to_record.append([match_id, timestamp, str(uid), player_name, team_name, name, ""])
                else:
                    lines.append(f"<@{uid}> : ランダム(エラー)")
            return "\n".join(lines) if lines else "なし"
            
        pick_a_str = get_pick_str(self.team_a, "チームA")
        pick_b_str = get_pick_str(self.team_b, "チームB")
        
        # 3. チームPICK (2列で横並び)
        embed.add_field(name="🔵 チームAのPICK", value=pick_a_str, inline=True)
        embed.add_field(name="🔴 チームBのPICK", value=pick_b_str, inline=True)
        
        # 最初から使いまわしているメインのメッセージ(entry_message)を最終更新する
        if self.entry_message:
            try:
                await self.entry_message.edit(content="✅ **全プレイヤーのピックが完了しました！**", embed=embed, view=None)
            except Exception as e:
                logger.error(f"メッセージ更新エラー: {e}")
                await self.original_interaction.channel.send(content="✅ **全プレイヤーのピックが完了しました！**", embed=embed)
        else:
            await self.original_interaction.channel.send(content="✅ **全プレイヤーのピックが完了しました！**", embed=embed)
            
        if details_to_record and self.sheet_manager:
            self.original_interaction.client.loop.create_task(
                asyncio.to_thread(self.sheet_manager.record_match_details, details_to_record)
            )