import discord
import random
import logging

logger = logging.getLogger('discord.banpick')

# ==========================================
# フェーズ管理用クラス
# ==========================================
class BanPickPhaseManager:
    """AチームとBチームの進行状況を管理し、両方完了したら結果を出すマネージャー"""
    def __init__(self, interaction, host, team_a, team_b, all_leaders, global_banned):
        self.original_interaction = interaction
        self.host = host
        self.team_a = team_a
        self.team_b = team_b
        self.all_leaders = all_leaders
        self.global_banned = global_banned
        
        self.banned_a = []
        self.banned_b = []
        self.a_done = False
        self.b_done = False
        
        # 進行用のメッセージインスタンスを保持
        self.msg_a = None
        self.msg_b = None

    async def report_ban_done(self, team_name, banned_list, interaction: discord.Interaction):
        if team_name == "A":
            self.banned_a = banned_list
            self.a_done = True
        else:
            self.banned_b = banned_list
            self.b_done = True

        await interaction.response.edit_message(content=f"✅ チーム{team_name}のBAN選択が完了しました！相手を待っています...", view=None)

        # 両方完了したら結果発表
        if self.a_done and self.b_done:
            await self.announce_results()

    async def announce_results(self):
        # 最終的にBANされた全リスト (重複防止のため 指導者名_文明名 のValueで管理)
        final_banned = set(self.global_banned + self.banned_a + self.banned_b)
        
        # ピック可能(生き残った)文明
        survivors = [L for L in self.all_leaders if f"{L['指導者名']}_{L['文明名']}" not in final_banned]
        
        embed = discord.Embed(title="🎉 CIV6 BAN/PICK 最終結果", color=discord.Color.gold())
        
        # BANされた「指導者名_文明名」から表示用に「指導者名」だけを抽出する関数
        def format_banned(banned_values):
            names = []
            for val in banned_values:
                parts = val.split('_')
                names.append(parts[0] if len(parts) > 0 else val)
            return "、".join(names) or "なし"

        # BANリスト表示
        ban_text = f"**【🌐 グローバルBAN】**\n" + format_banned(self.global_banned) + "\n\n"
        ban_text += f"**【🔵 チームAのBAN】**\n" + format_banned(self.banned_a) + "\n\n"
        ban_text += f"**【🔴 チームBのBAN】**\n" + format_banned(self.banned_b)
        embed.add_field(name="🚫 確定したBANリスト", value=ban_text, inline=False)
        
        # 生き残りリスト表示 (数が多いのでシンプルに)
        survivor_names = [f"{L.get('絵文字','')} {L['指導者名']}" for L in survivors]
        survivor_text = "、".join(survivor_names)
        if len(survivor_text) > 1000:
            survivor_text = survivor_text[:1000] + "...(省略)"
            
        embed.add_field(name=f"✅ ピック可能な文明 ({len(survivors)}人)", value=survivor_text, inline=False)
        embed.set_footer(text="残ったリストから自由にお好きな文明をピックしてください！GLHF！")
        
        await self.original_interaction.channel.send(content="**========= BAN/PICK 完了！ =========**", embed=embed)


# ==========================================
# フェーズ2: Poll風 分割ドロップダウンUI
# ==========================================
class ChunkedBanSelect(discord.ui.Select):
    def __init__(self, options, placeholder, max_bans):
        super().__init__(
            placeholder=placeholder,
            min_values=0,
            max_values=min(len(options), max_bans),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        # 選ぶたびにボタンの数値をリアルタイム更新する
        await self.view.update_button(interaction)

class ConfirmTargetBanButton(discord.ui.Button):
    def __init__(self, required_bans):
        super().__init__(style=discord.ButtonStyle.secondary, label=f"確定する (0/{required_bans})", custom_id="confirm_ban")
        self.required_bans = required_bans

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        total_selected = sum(len(s.values) for s in view.selects)
        
        if total_selected != self.required_bans:
            await interaction.response.send_message(f"⚠️ 合計 **{self.required_bans}個** 選んでください！（現在: {total_selected}個）", ephemeral=True)
            return
            
        # 選択内容を集約
        selected_leaders = []
        for s in view.selects:
            selected_leaders.extend(s.values)
            
        # マネージャーに完了を報告
        await view.manager.report_ban_done(view.team_name, selected_leaders, interaction)

class TargetBanView(discord.ui.View):
    def __init__(self, rep_id, required_bans, chunks, manager, team_name):
        super().__init__(timeout=None)
        self.rep_id = rep_id
        self.required_bans = required_bans
        self.manager = manager
        self.team_name = team_name
        self.selects = []
        
        # チャンク(25個ずつのリスト)ごとにドロップダウンを作る
        for chunk in chunks:
            if not chunk: continue
            first_name = chunk[0]["指導者名"][:3]
            last_name = chunk[-1]["指導者名"][:3]
            placeholder = f"[{first_name}〜{last_name}] から選ぶ ({len(chunk)}人) ▼"
            
            opts = []
            for L in chunk:
                # 重複エラーを防ぐため、Valueに文明名を結合して完全に一意のIDにする
                value_str = f"{L['指導者名']}_{L['文明名']}"
                opts.append(discord.SelectOption(
                    label=L["指導者名"], 
                    description=L["文明名"], 
                    emoji=L.get("絵文字") or None,
                    value=value_str
                ))
            
            sel = ChunkedBanSelect(opts, placeholder, required_bans)
            self.selects.append(sel)
            self.add_item(sel)
            
        self.confirm_btn = ConfirmTargetBanButton(required_bans)
        self.add_item(self.confirm_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # 管理者権限を持っているかチェック
        is_admin = interaction.user.guild_permissions.administrator
        
        # 代表者でなく、かつ管理者でもない場合は弾く
        if interaction.user.id != self.rep_id and not is_admin:
            await interaction.response.send_message(f"操作できるのはチーム{self.team_name}の代表者(<@{self.rep_id}>)のみです。", ephemeral=True)
            return False
        return True

    async def update_button(self, interaction: discord.Interaction):
        total = sum(len(s.values) for s in self.selects)
        self.confirm_btn.label = f"確定する ({total}/{self.required_bans})"
        
        # 規定数に達したらボタンを緑色(Success)にする
        if total == self.required_bans:
            self.confirm_btn.style = discord.ButtonStyle.success
        else:
            self.confirm_btn.style = discord.ButtonStyle.secondary
            
        await interaction.response.edit_message(view=self)


# ==========================================
# フェーズ1: グローバルBAN (代表者2名)
# ==========================================
class GlobalBanView(discord.ui.View):
    def __init__(self, host, team_a, team_b, global_pool, all_leaders, required_bans, sheet_manager):
        super().__init__(timeout=None)
        self.host = host
        self.team_a = team_a
        self.team_b = team_b
        
        self.rep_a = team_a[0] if team_a else host.id
        self.rep_b = team_b[0] if team_b else host.id
        
        self.global_pool = global_pool
        self.all_leaders = all_leaders
        self.required_bans = required_bans
        self.sheet_manager = sheet_manager
        
        self.banned_a = None
        self.banned_b = None
        
        options = []
        for L in global_pool:
            # 重複エラー回避のためValueを一意化
            value_str = f"{L['指導者名']}_{L['文明名']}"
            options.append(discord.SelectOption(
                label=L["指導者名"], 
                description=L["文明名"], 
                emoji=L.get("絵文字") or None,
                value=value_str
            ))
        
        self.select_a = discord.ui.Select(placeholder="🔵 チームA代表: グローバルBANを選択", min_values=1, max_values=1, options=options)
        self.select_a.callback = self.callback_a
        self.add_item(self.select_a)
        
        self.select_b = discord.ui.Select(placeholder="🔴 チームB代表: グローバルBANを選択", min_values=1, max_values=1, options=options)
        self.select_b.callback = self.callback_b
        self.add_item(self.select_b)

    async def callback_a(self, interaction: discord.Interaction):
        # チームA代表者、またはサーバー管理者のみ操作可能
        is_admin = interaction.user.guild_permissions.administrator
        if interaction.user.id != self.rep_a and not is_admin:
            return await interaction.response.send_message(f"チームAの代表者(<@{self.rep_a}>)のみ操作可能です。", ephemeral=True)
            
        self.banned_a = self.select_a.values[0]
        self.select_a.disabled = True
        await self.check_ready(interaction)

    async def callback_b(self, interaction: discord.Interaction):
        # チームB代表者、またはサーバー管理者のみ操作可能
        is_admin = interaction.user.guild_permissions.administrator
        if interaction.user.id != self.rep_b and not is_admin:
            return await interaction.response.send_message(f"チームBの代表者(<@{self.rep_b}>)のみ操作可能です。", ephemeral=True)
            
        self.banned_b = self.select_b.values[0]
        self.select_b.disabled = True
        await self.check_ready(interaction)

    async def check_ready(self, interaction: discord.Interaction):
        if self.select_a.disabled and self.select_b.disabled:
            # === 次のフェーズへの移行処理 ===
            banned_global = [b for b in [self.banned_a, self.banned_b] if b]
            
            # GBで選ばれた文明を除外したリストを作る (一意なValueで照合)
            available_leaders = [L for L in self.all_leaders if f"{L['指導者名']}_{L['文明名']}" not in banned_global]
            # 名前でソート
            available_leaders.sort(key=lambda x: x["指導者名"])
            
            # 25個ずつに分割 (チャンク化)
            chunks = [available_leaders[i:i + 25] for i in range(0, len(available_leaders), 25)]
            
            manager = BanPickPhaseManager(interaction, self.host, self.team_a, self.team_b, self.all_leaders, banned_global)
            
            view_a = TargetBanView(self.rep_a, self.required_bans, chunks, manager, "A")
            view_b = TargetBanView(self.rep_b, self.required_bans, chunks, manager, "B")
            
            # BANされた名前を表示用にフォーマット
            def format_banned(banned_values):
                names = []
                for val in banned_values:
                    parts = val.split('_')
                    names.append(parts[0] if len(parts) > 0 else val)
                return ", ".join(names)

            display_banned = format_banned(banned_global)
            await interaction.response.edit_message(content=f"🌐 **グローバルBANが確定しました: {display_banned}**\n続いて各チームのBANフェーズに移行します。", view=None)
            
            # A用とB用のパネルを2つのメッセージに分けて送信
            msg_a = await interaction.channel.send(f"🔵 **チームA 代表者 <@{self.rep_a}>** のBAN選択\n以下のリストから合計 **{self.required_bans}個** 選んで確定してください。\n*(※管理者は代理操作可能です)*", view=view_a)
            msg_b = await interaction.channel.send(f"🔴 **チームB 代表者 <@{self.rep_b}>** のBAN選択\n以下のリストから合計 **{self.required_bans}個** 選んで確定してください。\n*(※管理者は代理操作可能です)*", view=view_b)
            
            manager.msg_a = msg_a
            manager.msg_b = msg_b
        else:
            await interaction.response.edit_message(view=self)

# ==========================================
# エントリーポイント
# ==========================================
class BanPickStartView(discord.ui.View):
    def __init__(self, host: discord.Member, team_a: list, team_b: list, sheet_manager):
        super().__init__(timeout=None)
        self.host = host
        self.team_a = team_a
        self.team_b = team_b
        self.sheet_manager = sheet_manager

    @discord.ui.button(label="🚀 BAN/PICKを開始する", style=discord.ButtonStyle.danger, custom_id="civ_start_bp")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 開始ボタンもホスト、または管理者が押せるように緩和
        is_admin = interaction.user.guild_permissions.administrator
        if interaction.user.id != self.host.id and not is_admin:
            return await interaction.response.send_message("ホストまたは管理者のみが開始できます。", ephemeral=True)
        await interaction.response.defer()

        # 1. VC移動処理
        guild = interaction.guild
        host_vc = interaction.user.voice.channel if interaction.user.voice else None
        if host_vc:
            team_a_vc = discord.utils.find(lambda c: "チームa" in c.name.lower() or "チーム1" in c.name.lower(), guild.voice_channels)
            team_b_vc = discord.utils.find(lambda c: "チームb" in c.name.lower() or "チーム2" in c.name.lower(), guild.voice_channels)
            if team_a_vc and team_b_vc:
                for member in host_vc.members:
                    try:
                        if member.id in self.team_a: await member.move_to(team_a_vc)
                        elif member.id in self.team_b: await member.move_to(team_b_vc)
                    except Exception as e:
                        logger.error(f"VC移動エラー: {e}")
            else:
                await interaction.followup.send("⚠️ 「チームA」「チームB」という名前のVCが見つからなかったため、移動をスキップしました。", ephemeral=True)

        # 2. リーダーリストの取得とBAN数の計算
        all_leaders = self.sheet_manager.get_leaders() if hasattr(self.sheet_manager, "get_leaders") else []
        if not all_leaders:
            # 仮データ
            all_leaders = [{"指導者名": f"指導者{i}", "文明名": f"文明{i}", "グローバルBAN候補": 1 if i <= 10 else 0} for i in range(1, 78)]
            
        # グローバルBAN候補リストの抽出 (空白や文字列の「1」にも完全対応)
        global_pool = []
        for L in all_leaders:
            try:
                # 取得した値が '1' または 1 であれば抽出する
                if int(str(L.get("グローバルBAN候補", 0) or 0)) == 1:
                    global_pool.append(L)
            except ValueError:
                pass
                
        # 万が一「グローバルBAN候補」が1人もいなかった場合の保険
        if not global_pool:
            global_pool = all_leaders[:10]
            
        # チームの人数に応じたBAN数の算出 (4v4なら3個、5v5なら4個)
        team_size = max(len(self.team_a), len(self.team_b))
        required_bans = max(1, team_size - 1)

        # 3. グローバルBANUIの展開
        rep_a_id = self.team_a[0] if self.team_a else self.host.id
        rep_b_id = self.team_b[0] if self.team_b else self.host.id
        
        embed = discord.Embed(title="【🌐 フェーズ1: グローバルBAN】", description=f"両チームの代表者(<@{rep_a_id}>, <@{rep_b_id}>)は、以下のメニューから1つずつ除外する文明を選択してください。\n*(※管理者は代理操作が可能です)*", color=discord.Color.red())
        bp_view = GlobalBanView(self.host, self.team_a, self.team_b, global_pool, all_leaders, required_bans, self.sheet_manager)
        
        await interaction.followup.edit_message(message_id=interaction.message.id, content="⚔️ **BAN/PICKフェーズを開始します！**", embed=embed, view=bp_view)