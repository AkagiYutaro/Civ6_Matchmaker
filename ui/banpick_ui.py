import discord
import random
import logging
from logic.banpick_logic import (
    update_ban_count_in_sheet, 
    format_leader_list, 
    split_and_number_leaders, 
    prepare_leader_data
)

logger = logging.getLogger('discord.banpick')

# ==========================================
# フェーズ管理用クラス
# ==========================================
class BanPickPhaseManager:
    def __init__(self, interaction, host, team_a, team_b, all_leaders, global_banned, sheet_manager):
        self.original_interaction = interaction
        self.host = host
        self.team_a = team_a
        self.team_b = team_b
        self.all_leaders = all_leaders
        self.global_banned = global_banned
        self.sheet_manager = sheet_manager
        
        self.banned_a = []
        self.banned_b = []
        self.a_done = False
        self.b_done = False
        
        self.msg_a = None
        self.msg_b = None

    async def report_ban_done(self, team_name, banned_list, interaction: discord.Interaction):
        if team_name == "A":
            self.banned_a = banned_list
            self.a_done = True
        else:
            self.banned_b = banned_list
            self.b_done = True

        # 確定ボタンが押されたら、操作パネル(view)を消して待機メッセージに変更する
        await interaction.response.edit_message(content=f"✅ チーム{team_name}のBAN選択が完了しました！相手を待っています...", view=None)

        if self.a_done and self.b_done:
            await self.announce_results()

    async def announce_results(self):
        team_banned_uids = self.banned_a + self.banned_b
        team_banned_names = [L['clean_name'] for L in self.all_leaders if L['uid'] in team_banned_uids]
        if team_banned_names:
            self.original_interaction.client.loop.create_task(
                update_ban_count_in_sheet(self.sheet_manager, team_banned_names)
            )

        final_banned_uids = set(self.global_banned + self.banned_a + self.banned_b)
        survivors = [L for L in self.all_leaders if L['uid'] not in final_banned_uids]
        
        random.shuffle(survivors)
        
        list_a, list_b = split_and_number_leaders(survivors, 'final_disp_no')
        
        # 1. BAN一覧用Embed
        embed_ban = discord.Embed(title="BAN/PICK 結果", color=discord.Color.blue())
        ban_text = f"**【🌐 グローバルBAN】**\n" + format_leader_list(self.global_banned, self.all_leaders) + "\n\n"
        ban_text += f"**【🔵 チームAのBAN】**\n" + format_leader_list(self.banned_a, self.all_leaders) + "\n\n"
        ban_text += f"**【🔴 チームBのBAN】**\n" + format_leader_list(self.banned_b, self.all_leaders)
        embed_ban.add_field(name="🚫 確定したBAN", value=ban_text, inline=False)
        
        # 2. チームA候補用Embed
        embed_a = discord.Embed(color=discord.Color.blue())
        team_a_players = " ".join([f"<@{uid}>" for uid in self.team_a]) if self.team_a else "なし"
        embed_a.add_field(name="🔵 チームA プレイヤー", value=team_a_players, inline=False)
        
        # 3. チームB候補用Embed
        embed_b = discord.Embed(color=discord.Color.red())
        team_b_players = " ".join([f"<@{uid}>" for uid in self.team_b]) if self.team_b else "なし"
        embed_b.add_field(name="🔴 チームB プレイヤー", value=team_b_players, inline=False)
        
        def add_team_fields(target_embed, team_label, leader_list):
            chunk_size = 20
            chunks = [leader_list[i:i+chunk_size] for i in range(0, len(leader_list), chunk_size)]
            total_pages = max(1, len(chunks))
            for i, chunk in enumerate(chunks, 1):
                names = []
                for L in chunk:
                    emoji = L.get('emoji_text', '')
                    name = L['clean_name']
                    disp_no = L.get('final_disp_no', L.get('target_disp_no', 0))
                    names.append(f"{disp_no}. {emoji} {name}" if emoji else f"{disp_no}. {name}")
                
                val = "\n".join(names) if names else "なし"
                page_title = f"{team_label} - {i}/{total_pages}" if total_pages > 1 else team_label
                target_embed.add_field(name=page_title, value=val, inline=True)

        add_team_fields(embed_a, "🔵 チームA ピック候補", list_a)
        add_team_fields(embed_b, "🔴 チームB ピック候補", list_b)
        
        embed_b.set_footer(text="リストから指導者をピックしてください")
        
        # 3つのEmbedを同時に送信
        await self.original_interaction.channel.send(content="**========= BAN/PICK 完了！ =========**", embeds=[embed_ban, embed_a, embed_b])


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
        # 選択されるたびに親のViewを更新する
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
            
        selected_uids = []
        for s in view.selects:
            selected_uids.extend(s.values)
            
        # 確定ボタンが押されて初めてBAN処理を実行
        await view.manager.report_ban_done(view.team_name, selected_uids, interaction)

class TargetBanView(discord.ui.View):
    def __init__(self, rep_id, required_bans, chunks, manager, team_name):
        super().__init__(timeout=None)
        self.rep_id = rep_id
        self.required_bans = required_bans
        self.manager = manager
        self.team_name = team_name
        self.selects = []
        
        for chunk in chunks:
            if not chunk: continue
            
            first_no = chunk[0]['target_disp_no']
            last_no = chunk[-1]['target_disp_no']
            placeholder = f"[{first_no}〜{last_no}] から選択 ▼"
            
            opts = []
            for L in chunk:
                label_name = f"{L['target_disp_no']}. {L['clean_name']}"
                opts.append(discord.SelectOption(
                    label=label_name[:100], 
                    description=str(L.get("文明名", ""))[:100], 
                    emoji=L.get('emoji_obj'), 
                    value=L["uid"]
                ))
            
            sel = ChunkedBanSelect(opts, placeholder, required_bans)
            self.selects.append(sel)
            self.add_item(sel)
            
        self.confirm_btn = ConfirmTargetBanButton(required_bans)
        self.add_item(self.confirm_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        is_admin = interaction.user.guild_permissions.administrator
        if interaction.user.id != self.rep_id and not is_admin:
            await interaction.response.send_message(f"操作できるのはチーム{self.team_name}の代表者(<@{self.rep_id}>)のみです。", ephemeral=True)
            return False
        return True

    async def update_button(self, interaction: discord.Interaction):
        total = sum(len(s.values) for s in self.selects)
        self.confirm_btn.label = f"確定する ({total}/{self.required_bans})"
        
        if total == self.required_bans:
            self.confirm_btn.style = discord.ButtonStyle.success
        else:
            self.confirm_btn.style = discord.ButtonStyle.secondary
            
        # 💡 ここが魔法のコード！
        # 全てのドロップダウンの選択肢をループし、現在選ばれているものを「デフォルト(表示状態)」にする
        for select in self.selects:
            for option in select.options:
                option.default = option.value in select.values
                
        # メッセージを更新（これにより、他の人の画面でもドロップダウン内にチップが表示されます）
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
            label_name = f"{L.get('global_disp_no', L['No'])}. {L['clean_name']}"
            options.append(discord.SelectOption(
                label=label_name[:100], 
                description=str(L.get("文明名", ""))[:100], 
                emoji=L.get('emoji_obj'), 
                value=L["uid"]
            ))
        
        self.select_a = discord.ui.Select(placeholder="🔵 チームA代表: グローバルBANを選択", min_values=1, max_values=1, options=options)
        self.select_a.callback = self.callback_a
        self.add_item(self.select_a)
        
        self.select_b = discord.ui.Select(placeholder="🔴 チームB代表: グローバルBANを選択", min_values=1, max_values=1, options=options)
        self.select_b.callback = self.callback_b
        self.add_item(self.select_b)

    async def callback_a(self, interaction: discord.Interaction):
        is_admin = interaction.user.guild_permissions.administrator
        if interaction.user.id != self.rep_a and not is_admin:
            return await interaction.response.send_message(f"チームAの代表者(<@{self.rep_a}>)のみ操作可能です。", ephemeral=True)
            
        await interaction.response.defer()
        self.banned_a = self.select_a.values[0]
        self.select_a.disabled = True
        await self.check_ready(interaction)

    async def callback_b(self, interaction: discord.Interaction):
        is_admin = interaction.user.guild_permissions.administrator
        if interaction.user.id != self.rep_b and not is_admin:
            return await interaction.response.send_message(f"チームBの代表者(<@{self.rep_b}>)のみ操作可能です。", ephemeral=True)
            
        await interaction.response.defer()
        self.banned_b = self.select_b.values[0]
        self.select_b.disabled = True
        await self.check_ready(interaction)

    async def check_ready(self, interaction: discord.Interaction):
        if self.select_a.disabled and self.select_b.disabled:
            banned_global = [b for b in [self.banned_a, self.banned_b] if b]
            
            banned_names = [L['clean_name'] for L in self.all_leaders if L['uid'] in banned_global]
            if banned_names:
                interaction.client.loop.create_task(
                    update_ban_count_in_sheet(self.sheet_manager, banned_names)
                )
            
            available_leaders = [L for L in self.all_leaders if L["uid"] not in banned_global]
            
            manager = BanPickPhaseManager(interaction, self.host, self.team_a, self.team_b, self.all_leaders, banned_global, self.sheet_manager)
            
            random.shuffle(available_leaders)

            list_a, list_b = split_and_number_leaders(available_leaders, 'target_disp_no')

            embed_ban = discord.Embed(
                title="【フェーズ2: ターゲットBAN】", 
                description="グローバルBANが完了しました。続いて各チームのBANを行います。", 
                color=discord.Color.dark_grey()
            )
            embed_ban.add_field(name="🌐 確定したグローバルBAN", value=format_leader_list(banned_global, self.all_leaders), inline=False)
            
            embed_a = discord.Embed(color=discord.Color.blue())
            team_a_players = " ".join([f"<@{uid}>" for uid in self.team_a]) if self.team_a else "なし"
            embed_a.add_field(name="🔵 チームA プレイヤー", value=team_a_players, inline=False)
            
            embed_b = discord.Embed(color=discord.Color.red())
            team_b_players = " ".join([f"<@{uid}>" for uid in self.team_b]) if self.team_b else "なし"
            embed_b.add_field(name="🔴 チームB プレイヤー", value=team_b_players, inline=False)

            def add_team_fields(target_embed, team_label, leader_list):
                chunk_size = 20
                chunks = [leader_list[i:i+chunk_size] for i in range(0, len(leader_list), chunk_size)]
                total_pages = max(1, len(chunks))
                for i, chunk in enumerate(chunks, 1):
                    names = []
                    for L in chunk:
                        emoji = L.get('emoji_text', '')
                        name = L['clean_name']
                        disp_no = L.get('target_disp_no', 0)
                        names.append(f"{disp_no}. {emoji} {name}" if emoji else f"{disp_no}. {name}")
                    
                    val = "\n".join(names) if names else "なし"
                    page_title = f"{team_label} - {i}/{total_pages}" if total_pages > 1 else team_label
                    target_embed.add_field(name=page_title, value=val, inline=True)

            add_team_fields(embed_a, "🔵 チームA ピック候補", list_a)
            add_team_fields(embed_b, "🔴 チームB ピック候補", list_b)
            
            await interaction.edit_original_response(content=None, embeds=[embed_ban, embed_a, embed_b], view=None)
            
            chunks_a = [list_a[i:i + 25] for i in range(0, len(list_a), 25)]
            chunks_b = [list_b[i:i + 25] for i in range(0, len(list_b), 25)]
            
            view_a = TargetBanView(self.rep_a, self.required_bans, chunks_a, manager, "A")
            view_b = TargetBanView(self.rep_b, self.required_bans, chunks_b, manager, "B")
            
            msg_a = await interaction.channel.send(content=f"🔵 **チームA 代表者 <@{self.rep_a}>** のBAN選択\n以下のリストから合計 **{self.required_bans}個** 選んで確定してください。", view=view_a)
            msg_b = await interaction.channel.send(content=f"🔴 **チームB 代表者 <@{self.rep_b}>** のBAN選択\n以下のリストから合計 **{self.required_bans}個** 選んで確定してください。", view=view_b)
            
            manager.msg_a = msg_a
            manager.msg_b = msg_b
        else:
            await interaction.edit_original_response(view=self)


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

        # 2. リーダーリストの取得とデータ整形
        raw_leaders = self.sheet_manager.get_leaders() if hasattr(self.sheet_manager, "get_leaders") else []
        all_leaders, global_pool = prepare_leader_data(raw_leaders)
            
        required_bans = 5

        rep_a_id = self.team_a[0] if self.team_a else self.host.id
        rep_b_id = self.team_b[0] if self.team_b else self.host.id
        
        embed = discord.Embed(
            title="【🌐 フェーズ1: グローバルBAN】", 
            description=f"両チームの代表者(<@{rep_a_id}>, <@{rep_b_id}>)は、以下のメニューから1つずつ除外する文明を選択してください。\n*(※管理者は代理操作が可能です)*", 
            color=discord.Color.red()
        )
        bp_view = GlobalBanView(self.host, self.team_a, self.team_b, global_pool, all_leaders, required_bans, self.sheet_manager)
        
        await interaction.followup.edit_message(message_id=interaction.message.id, content="⚔️ **BAN/PICKフェーズを開始します！**", embed=embed, view=bp_view)