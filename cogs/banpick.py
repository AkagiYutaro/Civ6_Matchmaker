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
    if not sheet_manager or not banned_names:
        return
        
    def _update():
        try:
            ws = sheet_manager.sheet.worksheet("指導者")
            records = ws.get_all_records()
            headers = ws.row_values(1)
            
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

        await interaction.response.edit_message(content=f"✅ チーム{team_name}のBAN選択が完了しました！", view=None)

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

        ban_text = f"**【🌐 グローバルBAN】**\n{format_banned(self.global_banned)}\n\n**【🔵 チームAのBAN】**\n{format_banned(self.banned_a)}\n\n**【🔴 チームBのBAN】**\n{format_banned(self.banned_b)}"
        embed.add_field(name="🚫 確定したBANリスト", value=ban_text, inline=False)
        
        survivor_texts = [L['unique_name'] for L in survivors]
        half_idx = (len(survivor_texts) + 1) // 2
        
        list_a = survivor_texts[:half_idx]
        list_b = survivor_texts[half_idx:]
        
        embed.add_field(name=f"🔵 チームA ({len(list_a)}人)", value="\n".join(list_a) or "なし", inline=True)
        embed.add_field(name=f"🔴 チームB ({len(list_b)}人)", value="\n".join(list_b) or "なし", inline=True)
        embed.set_footer(text="残ったリストから自由にお好きな文明をピックしてください！GLHF！")
        
        await self.original_interaction.channel.send(content="**========= BAN/PICK 完了！ =========**", embed=embed)

# ==========================================
# UIクラス類 (TargetBanView, GlobalBanView 等)
# ==========================================
class ChunkedBanSelect(discord.ui.Select):
    def __init__(self, options, placeholder, max_bans):
        super().__init__(placeholder=placeholder, min_values=0, max_values=min(len(options), max_bans), options=options)
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
            await interaction.response.send_message(f"⚠️ 合計 {self.required_bans}個 選んでください！", ephemeral=True)
            return
        selected_uids = []
        for s in view.selects: selected_uids.extend(s.values)
        await view.manager.report_ban_done(view.team_name, selected_uids, interaction)

class TargetBanView(discord.ui.View):
    def __init__(self, rep_id, required_bans, chunks, manager, team_name):
        super().__init__(timeout=None)
        self.rep_id = rep_id
        self.manager = manager
        self.team_name = team_name
        self.selects = []
        for chunk in chunks:
            if not chunk: continue
            sel = ChunkedBanSelect([discord.SelectOption(label=f"{L['No']}. {L['clean_name']}", emoji=L.get('emoji_obj'), value=L["uid"]) for L in chunk], f"{chunk[0]['clean_name']}〜{chunk[-1]['clean_name']}", required_bans)
            self.selects.append(sel)
            self.add_item(sel)
        self.confirm_btn = ConfirmTargetBanButton(required_bans)
        self.add_item(self.confirm_btn)
    async def update_button(self, interaction: discord.Interaction):
        total = sum(len(s.values) for s in self.selects)
        self.confirm_btn.label = f"確定する ({total}/{self.confirm_btn.required_bans})"
        self.confirm_btn.style = discord.ButtonStyle.success if total == self.confirm_btn.required_bans else discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)

class GlobalBanView(discord.ui.View):
    def __init__(self, host, team_a, team_b, global_pool, all_leaders, required_bans, sheet_manager):
        super().__init__(timeout=None)
        self.host, self.team_a, self.team_b = host, team_a, team_b
        self.rep_a, self.rep_b = (team_a[0] if team_a else host.id), (team_b[0] if team_b else host.id)
        self.all_leaders, self.required_bans, self.sheet_manager = all_leaders, required_bans, sheet_manager
        options = [discord.SelectOption(label=f"{L['No']}. {L['clean_name']}", emoji=L.get('emoji_obj'), value=L["uid"]) for L in global_pool]
        self.select_a = discord.ui.Select(placeholder="🔵 チームA代表: BAN選択", options=options); self.select_a.callback = self.cb_a
        self.select_b = discord.ui.Select(placeholder="🔴 チームB代表: BAN選択", options=options); self.select_b.callback = self.cb_b
        self.add_item(self.select_a); self.add_item(self.select_b)
        self.b_a = None; self.b_b = None
    async def cb_a(self, interaction: discord.Interaction):
        self.b_a = self.select_a.values[0]; self.select_a.disabled = True; await self.check(interaction)
    async def cb_b(self, interaction: discord.Interaction):
        self.b_b = self.select_b.values[0]; self.select_b.disabled = True; await self.check(interaction)
    async def check(self, interaction: discord.Interaction):
        if self.select_a.disabled and self.select_b.disabled:
            banned = [b for b in [self.b_a, self.b_b] if b]
            manager = BanPickPhaseManager(interaction, self.host, self.team_a, self.team_b, self.all_leaders, banned, self.sheet_manager)
            await interaction.response.edit_message(content="グローバルBAN完了", view=None)
            available = [L for L in self.all_leaders if L["uid"] not in banned]
            chunks = [available[i:i + 25] for i in range(0, len(available), 25)]
            await interaction.channel.send("ターゲットBAN開始", view=TargetBanView(self.rep_a, self.required_bans, chunks, manager, "A"))
        else: await interaction.response.edit_message(view=self)

# ==========================================
# エントリーポイント
# ==========================================
class BanPickStartView(discord.ui.View):
    def __init__(self, host, team_a, team_b, sheet_manager):
        super().__init__(timeout=None)
        self.host, self.team_a, self.team_b, self.sheet_manager = host, team_a, team_b, sheet_manager

    @discord.ui.button(label="🚀 BAN/PICKを開始する", style=discord.ButtonStyle.danger)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        raw = self.sheet_manager.get_leaders()
        all_leaders = []
        for i, L in enumerate(raw):
            # 💡 Emoji_Discord_Nm + Emoji_Discord_ID を組み合わせて生成
            nm = str(L.get('Emoji_Discord_Nm', '')).strip()
            id_val = str(L.get('Emoji_Discord_ID', '')).strip()
            emoji_obj = None
            if nm and id_val:
                try:
                    # Discordの形式 <:name:id> を作成
                    emoji_str = f"<:{nm}:{id_val}>"
                    emoji_obj = discord.PartialEmoji.from_str(emoji_str)
                except: pass
            
            L.update({'uid': f"L{i}", 'clean_name': L.get('指導者名', 'Unknown'), 'emoji_obj': emoji_obj})
            all_leaders.append(L)
            
        pool = [L for L in all_leaders if str(L.get("グローバルBANFLG", "")).strip() == "1"]
        view = GlobalBanView(self.host, self.team_a, self.team_b, pool, all_leaders, 3, self.sheet_manager)
        await interaction.response.edit_message(content="BAN/PICKフェーズ開始", view=view)