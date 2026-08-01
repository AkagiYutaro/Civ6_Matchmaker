import time
import asyncio
import random
import datetime
import logging
import discord
from logic.banpick_logic import format_leader_list

logger = logging.getLogger('discord.pick_logic')
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
    def __init__(self, interaction, host, team_a, team_b, survivors, all_leaders, banned_global, banned_a, banned_b, sheet_manager, chosen_map=None, max_vote_val=0, match_id=None):
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
        
        self.chosen_map = chosen_map
        self.max_vote_val = max_vote_val
        self.match_id = match_id or "Match-Unknown"
        
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
                    final_uid = random.choice(available) if available else None
                
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
        embed = discord.Embed(title=f"{self.match_id}", color=discord.Color.yellow())
        
        # 🗺️ Map表示
        if self.chosen_map:
            map_str = f"**{self.chosen_map}** （{self.max_vote_val}票獲得）" if self.max_vote_val > 0 else f"**{self.chosen_map}**"
            embed.add_field(name="\u200B", value=f"** 🗺️ Map **\n{map_str}", inline=False)
            # embed.add_field(name="\u200B", value="\u200B", inline=False)
            
        # 1. メインBAN
        global_str = format_leader_list(self.banned_global, self.all_leaders)
        embed.add_field(name="\u200B", value=f"** 🌐 メインBAN**\n{global_str}", inline=False)
        # embed.add_field(name="\u200B", value="\u200B", inline=False)
        
        # 2. チームBAN
        ban_a_str = format_leader_list(self.banned_a, self.all_leaders)
        ban_b_str = format_leader_list(self.banned_b, self.all_leaders)
        embed.add_field(name="\u200B", value=f"** 🚫 BAN**\n**🔵 チームA**\n{ban_a_str}", inline=True)
        embed.add_field(name="\u200B", value=f"\u200B\n**🔴 チームB**\n{ban_b_str}", inline=True)
        
        embed.add_field(name="\u200B", value="\u200B", inline=False)
        
        now_jst = datetime.datetime.now(JST)
        timestamp = now_jst.strftime("%Y/%m/%d %H:%M:%S")
        details_to_record = []
        
        picked_leader_names = []
        
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
                    details_to_record.append([self.match_id, timestamp, str(uid), player_name, team_name, name, ""])
                    picked_leader_names.append(name)
                else:
                    lines.append(f"<@{uid}> : ランダム(エラー)")
            return "\n".join(lines) if lines else "なし"
            
        pick_a_str = get_pick_str(self.team_a, "チームA")
        pick_b_str = get_pick_str(self.team_b, "チームB")
        
        # 3. PICK
        embed.add_field(name="\u200B", value=f"** ✅ PICK**\n**🔵 チームA**\n{pick_a_str}", inline=True)
        embed.add_field(name="\u200B", value=f" \u200B\n**🔴 チームB**\n{pick_b_str}", inline=True)
        # embed.add_field(name="\u200B", value="\u200B", inline=False)
        
        view = MatchResultView(self, self.match_id)
        
        if self.entry_message:
            try:
                await self.entry_message.edit(content=None, embed=embed, view=view)
            except Exception as e:
                logger.error(f"メッセージ更新エラー: {e}")
                await self.original_interaction.channel.send(content=None, embed=embed, view=view)
        else:
            await self.original_interaction.channel.send(content=None, embed=embed, view=view)
            
        if details_to_record and self.sheet_manager:
            self.original_interaction.client.loop.create_task(
                asyncio.to_thread(self.sheet_manager.record_match_details, details_to_record)
            )
            # 指導者シートのPICK回数もカウントアップする
            self.original_interaction.client.loop.create_task(
                asyncio.to_thread(self.sheet_manager.update_pick_count, picked_leader_names)
            )


# ==========================================
# 勝敗記録用UI
# ==========================================
class MatchResultView(discord.ui.View):
    def __init__(self, manager, match_id):
        super().__init__(timeout=None)
        self.manager = manager
        self.match_id = match_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        is_admin = interaction.user.guild_permissions.administrator
        all_players = self.manager.team_a + self.manager.team_b
        if interaction.user.id not in all_players and not is_admin:
            await interaction.response.send_message("この対戦の参加者、または管理者のみが勝敗を記録できます。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🔵 チームA 勝利", style=discord.ButtonStyle.primary, custom_id="win_team_a")
    async def btn_win_a(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_result(interaction, "チームA")

    @discord.ui.button(label="🔴 チームB 勝利", style=discord.ButtonStyle.danger, custom_id="win_team_b")
    async def btn_win_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_result(interaction, "チームB")

    async def process_result(self, interaction: discord.Interaction, win_team: str):
        # ボタンを無効化
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        
        await interaction.followup.send(f"🔄 勝敗({win_team})を記録し、レートを計算中です...", ephemeral=True)
        
        if self.manager.sheet_manager:
            # 勝敗記録タスク
            self.manager.original_interaction.client.loop.create_task(
                asyncio.to_thread(self.manager.sheet_manager.update_match_result, self.match_id, win_team)
            )
            
            # レートの計算と更新
            from logic.rate_logic import calculate_new_rates
            all_ids = self.manager.team_a + self.manager.team_b
            current_rates = await asyncio.to_thread(self.manager.sheet_manager.get_player_rates, all_ids)
            
            rate_results = calculate_new_rates(self.manager.team_a, self.manager.team_b, win_team, current_rates)
            
            new_rates_to_save = {uid: data["new"] for uid, data in rate_results.items()}
            self.manager.original_interaction.client.loop.create_task(
                asyncio.to_thread(self.manager.sheet_manager.update_player_rates, new_rates_to_save)
            )

            # 元のEmbedに勝敗結果を追記し、レート確認用の専用ボタンUIに差し替える
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.gold()
            embed.add_field(name="\u200B", value=f"** 🏆 対戦結果**\n**{win_team} WIN**", inline=False)
            
            from ui.rate_ui import RateCheckView
            rate_view = RateCheckView(rate_results, self.manager)
            
            await interaction.message.edit(content=None, embed=embed, view=rate_view)