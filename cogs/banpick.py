import discord
import random
import logging
import asyncio
import gspread

logger = logging.getLogger('discord.banpick')

# ==========================================
# スプレッドシート カウントアップ用非同期処理
# ==========================================
async def update_ban_count_in_sheet(sheet_manager, banned_names):
    """
    BANされた指導者の名前リストを受け取り、非同期でスプレッドシートのBAN回数を更新する。
    """
    if not sheet_manager or not banned_names:
        return
        
    def _update():
        try:
            ws = sheet_manager.sheet.worksheet("指導者")
            records = ws.get_all_records()
            headers = ws.row_values(1)
            
            # BAN回数列、PICK回数列がない場合は自動追加
            needs_update = False
            if "BAN回数" not in headers:
                headers.append("BAN回数")
                needs_update = True
            if "PICK回数" not in headers:
                headers.append("PICK回数")
                needs_update = True
                
            if needs_update:
                ws.update("A1", [headers])
                
            ban_col_idx = headers.index("BAN回数") + 1
            
            updates = []
            for row_idx, row in enumerate(records, start=2):
                leader_name = str(row.get("指導者名", "")).strip()
                if leader_name in banned_names:
                    current_val = row.get("BAN回数", 0)
                    try:
                        count = int(current_val) if current_val != "" else 0
                    except ValueError:
                        count = 0
                    
                    updates.append({
                        'range': gspread.utils.rowcol_to_a1(row_idx, ban_col_idx),
                        'values': [[count + 1]]
                    })
                    
            if updates:
                ws.batch_update(updates)
                logger.info(f"[SUCCESS] スプレッドシートのBAN回数を更新しました: {banned_names}")
        except Exception as e:
            logger.error(f"[ERROR] BAN回数の更新に失敗: {e}")

    await asyncio.to_thread(_update)


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
        
        embed = discord.Embed(title="🎉 CIV6 BAN/PICK 最終結果", color=discord.Color.gold())
        
        def format_banned(uid_list):
            names = []
            for uid in uid_list:
                leader = next((l for l in self.all_leaders if l['uid'] == uid), None)
                if leader:
                    names.append(leader['unique_name'])
            return "、\n".join(names) if names else "なし"

        ban_text = f"**【🌐 グローバルBAN】**\n" + format_banned(self.global_banned) + "\n\n"
        ban_text += f"**【🔵 チームAのBAN】**\n" + format_banned(self.banned_a) + "\n\n"
        ban_text += f"**【🔴 チームBのBAN】**\n" + format_banned(self.banned_b)
        embed.add_field(name="🚫 確定したBANリスト", value=ban_text, inline=False)
        
        # 💡 生き残りリストを半分に分割して表示
        survivor_texts = [L['unique_name'] for L in survivors]
        half_idx = (len(survivor_texts) + 1) // 2
        
        list_a = survivor_texts[:half_idx]
        list_b = survivor_texts[half_idx:]
        
        display_a = "\n".join(list_a)
        display_b = "\n".join(list_b)
        
        if len(display_a) > 1024: display_a = display_a[:1000] + "...\n(以下略)"
        if len(display_b) > 1024: display_b = display_b[:1000] + "...\n(以下略)"
            
        embed.add_field(name=f"🔵 チームA側 リスト ({len(list_a)}人)", value=display_a, inline=True)
        embed.add_field(name=f"🔴 チームB側 リスト ({len(list_b)}人)", value=display_b, inline=True)
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
            first_name = chunk[0]["clean_name"][:3]
            last_name = chunk[-1]["clean_name"][:3]
            placeholder = f"[{first_name}〜{last_name}] から選ぶ ({len(chunk)}人) ▼"
            
            opts = []
            for L in chunk:
                label_name = f"{L['No']}. {L['clean_name']}"
                opts.append(discord.SelectOption(
                    label=label_name[:100], 
                    description=str(L.get("文明名", ""))[:100], 
                    emoji=L.get('emoji_obj'), # 事前生成したオブジェクトを使用
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
            label_name = f"{L['No']}. {L['clean_name']}"
            options.append(discord.SelectOption(
                label=label_name[:100], 
                description=str(L.get("文明名", ""))[:100], 
                emoji=L.get('emoji_obj'), # 事前生成したオブジェクトを使用
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
            
        self.banned_a = self.select_a.values[0]
        self.select_a.disabled = True
        await self.check_ready(interaction)

    async def callback_b(self, interaction: discord.Interaction):
        is_admin = interaction.user.guild_permissions.administrator
        if interaction.user.id != self.rep_b and not is_admin:
            return await interaction.response.send_message(f"チームBの代表者(<@{self.rep_b}>)のみ操作可能です。", ephemeral=True)
            
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
            available_leaders.sort(key=lambda x: x["clean_name"])
            
            manager = BanPickPhaseManager(interaction, self.host, self.team_a, self.team_b, self.all_leaders, banned_global, self.sheet_manager)
            
            def format_banned(uid_list):
                names = []
                for uid in uid_list:
                    leader = next((l for l in self.all_leaders if l['uid'] == uid), None)
                    if leader:
                        names.append(leader['unique_name'])
                return "、\n".join(names) if names else "なし"
                
            # 💡 リストを半分に分割してAとBに割り当てる
            survivor_texts = [L['unique_name'] for L in available_leaders]
            half_idx = (len(survivor_texts) + 1) // 2
            
            list_a = survivor_texts[:half_idx]
            list_b = survivor_texts[half_idx:]
            
            display_a = "\n".join(list_a)
            display_b = "\n".join(list_b)
            
            if len(display_a) > 1024: display_a = display_a[:1000] + "...\n(以下略)"
            if len(display_b) > 1024: display_b = display_b[:1000] + "...\n(以下略)"

            inter_embed = discord.Embed(
                title="【フェーズ2: ターゲットBAN】", 
                description="グローバルBANが完了しました。続いて各チームのBANを行います。", 
                color=discord.Color.blue()
            )
            inter_embed.add_field(name="🌐 確定したグローバルBAN", value=format_banned(banned_global), inline=False)
            
            inter_embed.add_field(name=f"🔵 チームA側 リスト ({len(list_a)}人)", value=display_a, inline=True)
            inter_embed.add_field(name=f"🔴 チームB側 リスト ({len(list_b)}人)", value=display_b, inline=True)

            await interaction.response.edit_message(content=None, embed=inter_embed, view=None)
            
            chunks = [available_leaders[i:i + 25] for i in range(0, len(available_leaders), 25)]
            view_a = TargetBanView(self.rep_a, self.required_bans, chunks, manager, "A")
            view_b = TargetBanView(self.rep_b, self.required_bans, chunks, manager, "B")
            
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
        if not raw_leaders:
            raw_leaders = [{"指導者名": f"指導者{i}", "文明名": f"文明{i}", "グローバルBANFLG": 1 if i <= 10 else 0} for i in range(1, 78)]
            
        all_leaders = []
        for i, L in enumerate(raw_leaders):
            leader_data = L.copy()
            
            no_val = str(leader_data.get("No", "")).strip()
            if not no_val: no_val = str(i + 1)
            
            leader_name = leader_data.get('指導者名', 'Unknown')
            
            # 💡 ID（数字のみ）が入力されていても自動で絵文字形式に変換する処理
            emoji_str = str(leader_data.get('絵文字（Discord ID）', '')).strip()
            emoji_obj = None
            emoji_text = ""
            
            if emoji_str:
                if emoji_str.isdigit():
                    # 数字のみ(ID)の場合はDiscord絵文字フォーマットに組み立て
                    emoji_id = int(emoji_str)
                    emoji_obj = discord.PartialEmoji(name="icon", id=emoji_id)
                    emoji_text = f"<:icon:{emoji_id}>"
                elif emoji_str.startswith('<') and emoji_str.endswith('>'):
                    # <...:123> のような絵文字形式の場合
                    try:
                        emoji_obj = discord.PartialEmoji.from_str(emoji_str)
                        emoji_text = emoji_str
                    except:
                        emoji_text = emoji_str
                else:
                    emoji_obj = emoji_str
                    emoji_text = emoji_str
            
            unique_id = f"leader_id_{i}_{leader_name}"
            
            # テキスト表示用 (No. 指導者名 <:アイコン:>)
            display_name = f"{no_val}. {leader_name}"
            if emoji_text:
                display_name += f" {emoji_text}"
                
            leader_data['unique_name'] = display_name
            leader_data['clean_name'] = leader_name
            leader_data['No'] = no_val
            leader_data['uid'] = unique_id
            leader_data['emoji_obj'] = emoji_obj # ドロップダウン用に保存
            
            all_leaders.append(leader_data)

        # グローバルBAN候補リストの抽出
        global_pool = []
        for L in all_leaders:
            val = L.get("グローバルBANFLG", L.get("グローバルBAN候補"))
            try:
                if int(str(val or 0).strip()) == 1:
                    global_pool.append(L)
            except ValueError:
                pass
                
        if len(global_pool) > 25:
            global_pool = global_pool[:25]
        
        if not global_pool:
            global_pool = all_leaders[:10]
            
        team_size = max(len(self.team_a), len(self.team_b))
        required_bans = max(1, team_size - 1)

        rep_a_id = self.team_a[0] if self.team_a else self.host.id
        rep_b_id = self.team_b[0] if self.team_b else self.host.id
        
        embed = discord.Embed(title="【🌐 フェーズ1: グローバルBAN】", description=f"両チームの代表者(<@{rep_a_id}>, <@{rep_b_id}>)は、以下のメニューから1つずつ除外する文明を選択してください。\n*(※管理者は代理操作が可能です)*", color=discord.Color.red())
        bp_view = GlobalBanView(self.host, self.team_a, self.team_b, global_pool, all_leaders, required_bans, self.sheet_manager)
        
        await interaction.followup.edit_message(message_id=interaction.message.id, content="⚔️ **BAN/PICKフェーズを開始します！**", embed=embed, view=bp_view)