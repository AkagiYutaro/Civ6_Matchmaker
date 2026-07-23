import discord
import asyncio
import time
import random
import logging
from logic.banpick_logic import format_leader_list

logger = logging.getLogger('discord.pick')

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

# ==========================================
# PICKフェーズ管理
# ==========================================
class PickPhaseManager:
    def __init__(self, interaction, host, team_a, team_b, survivors, all_leaders, banned_global, banned_a, banned_b, sheet_manager):
        self.original_interaction = interaction
        self.host = host
        self.team_a = team_a
        self.team_b = team_b
        self.survivors = survivors
        self.all_leaders = all_leaders
        
        # 最終結果表示用
        self.banned_global = banned_global
        self.banned_a = banned_a
        self.banned_b = banned_b
        
        # {user_id: {"leader": uid, "confirmed": bool}}
        self.picks = {} 
        self.is_completed = False
        
        self.duration = get_pick_timer(sheet_manager)
        self.end_time = int(time.time()) + self.duration
        self.timeout_task = None
        self.entry_message = None

    async def start(self):
        """フェーズの開始とタイマーの起動"""
        view = PickEntryView(self)
        content = f"📢 **指導者ピックフェーズ**\n終了時刻: <t:{self.end_time}:R>\n各プレイヤーは操作ボタンから使用する指導者を仮選択し、確定してください。\n*(※確定後は変更できません)*"
        
        self.entry_message = await self.original_interaction.channel.send(content=content, view=view)
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
                # 仮選択があれば優先。他人に取られていたらランダム
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
        if self.entry_message:
            try:
                await self.entry_message.edit(content="✅ **全プレイヤーのピックが完了しました！**", view=None)
            except: pass
            
        embed = discord.Embed(title="🎉 CIV6 最終結果 (BAN / PICK)", color=discord.Color.gold())
        
        # 1. 確定したBAN
        global_str = format_leader_list(self.banned_global, self.all_leaders)
        embed.add_field(name="🌐 1. 確定したBAN (グローバル)", value=global_str, inline=False)
        
        # 2. チームBAN
        ban_a_str = format_leader_list(self.banned_a, self.all_leaders)
        ban_b_str = format_leader_list(self.banned_b, self.all_leaders)
        embed.add_field(name="🚫 2. 【チームAのBAN】", value=ban_a_str, inline=True)
        embed.add_field(name="🚫 2. 【チームBのBAN】", value=ban_b_str, inline=True)
        embed.add_field(name="\u200B", value="\u200B", inline=True) # レイアウト調整用の空白
        
        # 3. チームPICK
        def get_pick_str(team_ids):
            lines = []
            for uid in team_ids:
                l_id = self.picks.get(uid, {}).get("leader")
                leader = next((l for l in self.all_leaders if l['uid'] == l_id), None)
                if leader:
                    emoji = leader.get('emoji_text', '')
                    name = leader['clean_name']
                    lines.append(f"<@{uid}> : {emoji} **{name}**")
                else:
                    lines.append(f"<@{uid}> : ランダム(エラー)")
            return "\n".join(lines) if lines else "なし"
            
        pick_a_str = get_pick_str(self.team_a)
        pick_b_str = get_pick_str(self.team_b)
        
        embed.add_field(name="🔵 3. 【チームAのPICK】", value=pick_a_str, inline=True)
        embed.add_field(name="🔴 3. 【チームBのPICK】", value=pick_b_str, inline=True)
        embed.add_field(name="\u200B", value="\u200B", inline=True)
        
        embed.set_footer(text="ゲームを開始してください！ GLHF！")
        await self.original_interaction.channel.send(embed=embed)


# ==========================================
# プレイヤー用 操作UI (ephemeral)
# ==========================================
class PickSelect(discord.ui.Select):
    def __init__(self, options, placeholder):
        super().__init__(placeholder=placeholder, min_values=0, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        uid = self.values[0] if self.values else None
        
        if uid:
            self.view.manager.picks[interaction.user.id] = {"leader": uid, "confirmed": False}
            self.view.selected_uid = uid
            
        # 同じ画面にあるすべてのドロップダウンの表示を同期（チップ化）
        for select in self.view.selects:
            for opt in select.options:
                opt.default = (opt.value == self.view.selected_uid)
                
        self.view.confirm_btn.disabled = not bool(self.view.selected_uid)
        await interaction.response.edit_message(view=self.view)


class PickConfirmButton(discord.ui.Button):
    def __init__(self, disabled):
        super().__init__(style=discord.ButtonStyle.success, label="ピックを確定する", disabled=disabled)
        
    async def callback(self, interaction: discord.Interaction):
        uid = self.view.selected_uid
        # 直前に他人に確定されていないかチェック
        is_used = any(d["leader"] == uid and d["confirmed"] for user_id, d in self.view.manager.picks.items() if user_id != interaction.user.id)
        if is_used:
            return await interaction.response.send_message("⚠️ その指導者は直前に他のプレイヤーに確定されました。別の指導者を選び直してください。", ephemeral=True)
            
        self.view.manager.picks[interaction.user.id] = {"leader": uid, "confirmed": True}
        await interaction.response.edit_message(content="✅ 指導者を確定しました！他のプレイヤーを待っています...", view=None, embed=None)
        await self.view.manager.check_all_completed()


class PlayerPickView(discord.ui.View):
    def __init__(self, user_id, manager):
        super().__init__(timeout=None)
        self.manager = manager
        self.selected_uid = manager.picks.get(user_id, {}).get("leader")
        self.selects = []
        
        # 既に他人が「確定」した指導者はリストから除外する
        confirmed_uids = [d["leader"] for uid, d in manager.picks.items() if d["confirmed"] and uid != user_id]
        available = [L for L in manager.survivors if L['uid'] not in confirmed_uids]
        
        chunks = [available[i:i+25] for i in range(0, len(available), 25)]
        
        for chunk in chunks:
            if not chunk: continue
            first_no = chunk[0].get('final_disp_no', 0)
            last_no = chunk[-1].get('final_disp_no', 0)
            placeholder = f"[{first_no}〜{last_no}] から選択 ▼"
            
            opts = []
            for L in chunk:
                is_default = (L['uid'] == self.selected_uid)
                opts.append(discord.SelectOption(
                    label=f"{L.get('final_disp_no', 0)}. {L['clean_name']}"[:100],
                    description=str(L.get("文明名", ""))[:100],
                    emoji=L.get('emoji_obj'),
                    value=L['uid'],
                    default=is_default
                ))
            
            sel = PickSelect(opts, placeholder)
            self.selects.append(sel)
            self.add_item(sel)
            
        self.confirm_btn = PickConfirmButton(disabled=(not self.selected_uid))
        self.add_item(self.confirm_btn)


# ==========================================
# エントリ用UI (公開チャンネル用)
# ==========================================
class PickEntryView(discord.ui.View):
    def __init__(self, manager):
        super().__init__(timeout=None)
        self.manager = manager

    def format_team_status(self, team_ids):
        lines = []
        for uid in team_ids:
            data = self.manager.picks.get(uid, {"leader": None, "confirmed": False})
            l_id = data["leader"]
            is_conf = data["confirmed"]
            
            if l_id:
                leader = next((l for l in self.manager.all_leaders if l['uid'] == l_id), None)
                name_str = f"{leader.get('emoji_text','')} {leader['clean_name']}" if leader else "不明"
                status = "✅ 確定済" if is_conf else "⏳ 仮選択中"
                lines.append(f"・<@{uid}> : {name_str} ({status})")
            else:
                lines.append(f"・<@{uid}> : 未選択")
        return "\n".join(lines)

    @discord.ui.button(label="🔵 A: ピック操作", style=discord.ButtonStyle.primary, row=0)
    async def btn_op_a(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.manager.team_a:
            return await interaction.response.send_message("チームAのプレイヤーのみ操作可能です。", ephemeral=True)
        if self.manager.picks.get(interaction.user.id, {}).get("confirmed"):
            return await interaction.response.send_message("既に確定済みです。", ephemeral=True)
            
        view = PlayerPickView(interaction.user.id, self.manager)
        await interaction.response.send_message("使用する指導者を選んでください:", view=view, ephemeral=True)

    @discord.ui.button(label="🔵 A: 選択状況の確認", style=discord.ButtonStyle.secondary, row=0)
    async def btn_chk_a(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.manager.team_a and interaction.user.id != self.manager.host.id:
            return await interaction.response.send_message("チームAのメンバーのみ確認可能です。", ephemeral=True)
        
        text = "**🔵 チームA メンバーの選択状況**\n" + self.format_team_status(self.manager.team_a)
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="🔴 B: ピック操作", style=discord.ButtonStyle.danger, row=1)
    async def btn_op_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.manager.team_b:
            return await interaction.response.send_message("チームBのプレイヤーのみ操作可能です。", ephemeral=True)
        if self.manager.picks.get(interaction.user.id, {}).get("confirmed"):
            return await interaction.response.send_message("既に確定済みです。", ephemeral=True)
            
        view = PlayerPickView(interaction.user.id, self.manager)
        await interaction.response.send_message("使用する指導者を選んでください:", view=view, ephemeral=True)

    @discord.ui.button(label="🔴 B: 選択状況の確認", style=discord.ButtonStyle.secondary, row=1)
    async def btn_chk_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.manager.team_b and interaction.user.id != self.manager.host.id:
            return await interaction.response.send_message("チームBのメンバーのみ確認可能です。", ephemeral=True)
        
        text = "**🔴 チームB メンバーの選択状況**\n" + self.format_team_status(self.manager.team_b)
        await interaction.response.send_message(text, ephemeral=True)


async def start_pick_phase(interaction, host, team_a, team_b, survivors, all_leaders, banned_global, banned_a, banned_b, sheet_manager):
    """他ファイルから呼び出すためのエントリポイント"""
    manager = PickPhaseManager(interaction, host, team_a, team_b, survivors, all_leaders, banned_global, banned_a, banned_b, sheet_manager)
    await manager.start()