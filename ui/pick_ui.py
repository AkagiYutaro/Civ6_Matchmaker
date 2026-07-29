import discord
import logging
import random
from logic.pick_logic import PickPhaseManager
from logic.banpick_logic import split_and_number_leaders, format_leader_list

logger = logging.getLogger('discord.pick_ui')

class ChunkedPickSelect(discord.ui.Select):
    def __init__(self, options, placeholder):
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_select(interaction, self)

class ConfirmPickButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.success, label="確定する", custom_id="confirm_pick", disabled=True)

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_confirm(interaction)

class PickLeaderView(discord.ui.View):
    def __init__(self, manager, chunks, team_ids, list_name):
        super().__init__(timeout=None)
        self.manager = manager
        self.team_ids = team_ids
        self.list_name = list_name
        self.selects = []
        
        for chunk in chunks:
            if not chunk: continue
            
            first_no = chunk[0].get('final_disp_no', 0)
            last_no = chunk[-1].get('final_disp_no', 0)
            placeholder = f"[{first_no}〜{last_no}] から選択 ▼"
            
            opts = []
            for L in chunk:
                label_name = f"{L.get('final_disp_no', 0)}. {L['clean_name']}"
                opts.append(discord.SelectOption(
                    label=label_name[:100], 
                    description=str(L.get("文明名", ""))[:100], 
                    emoji=L.get('emoji_obj'), 
                    value=L["uid"]
                ))
            
            sel = ChunkedPickSelect(opts, placeholder)
            self.selects.append(sel)
            self.add_item(sel)
            
        self.confirm_btn = ConfirmPickButton()
        self.add_item(self.confirm_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.team_ids:
            await interaction.response.send_message("このリストからはピックできません（別チーム用です）。", ephemeral=True)
            return False
        return True

    async def handle_select(self, interaction: discord.Interaction, active_select):
        user_id = interaction.user.id
        selected_uid = active_select.values[0]
        
        for s in self.selects:
            if s != active_select:
                s.values = []
                
        user_data = self.manager.picks.get(user_id, {})
        if user_data.get("confirmed"):
            return await interaction.response.send_message("既に確定済みです。", ephemeral=True)
            
        is_used = any(d.get("leader") == selected_uid for uid, d in self.manager.picks.items() if uid != user_id)
        if is_used:
            return await interaction.response.send_message("⚠️ その指導者はすでに他の人が選択（または仮選択）しています！", ephemeral=True)
            
        self.manager.picks[user_id] = {"leader": selected_uid, "confirmed": False}
        self.confirm_btn.disabled = False
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("✅ 仮選択しました。準備ができたら「確定する」を押してください。\n*(同じチームの人は状況確認ボタンからあなたの仮選択を見ることができます)*", ephemeral=True)

    async def handle_confirm(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        user_data = self.manager.picks.get(user_id, {})
        
        if not user_data.get("leader"):
            return await interaction.response.send_message("先に指導者を選択してください。", ephemeral=True)
            
        user_data["confirmed"] = True
        self.manager.picks[user_id] = user_data
        
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ **あなたのピックが確定しました！**\n全員の選択が終わるまでお待ちください。", view=None)
        
        await self.manager.check_all_completed()

class PickEntryView(discord.ui.View):
    def __init__(self, manager):
        super().__init__(timeout=None)
        self.manager = manager

    def format_team_status(self, team_ids):
        lines = []
        for uid in team_ids:
            data = self.manager.picks.get(uid, {})
            status = "✅確定" if data.get("confirmed") else "⏳仮選択中" if data.get("leader") else "未選択"
            
            l_id = data.get("leader")
            leader = next((l for l in self.manager.all_leaders if l['uid'] == l_id), None) if l_id else None
            l_str = f"({leader['emoji_text']} {leader['clean_name']})" if leader else ""
            
            member = self.manager.original_interaction.guild.get_member(uid)
            name = member.display_name if member else f"User {uid}"
            lines.append(f"・{name} : {status} {l_str}")
        return "\n".join(lines) if lines else "なし"

    @discord.ui.button(label="🔵 A: 指導者をピックする", style=discord.ButtonStyle.primary, row=0)
    async def btn_pick_a(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.manager.team_a:
            return await interaction.response.send_message("あなたはチームAではありません。", ephemeral=True)
            
        data = self.manager.picks.get(interaction.user.id, {})
        if data.get("confirmed"):
            return await interaction.response.send_message("既に確定済みです！", ephemeral=True)
            
        survivors = self.manager.survivors
        half_idx = (len(survivors) + 1) // 2
        list_a = survivors[:half_idx]
        chunks_a = [list_a[i:i + 25] for i in range(0, len(list_a), 25)]
        
        view = PickLeaderView(self.manager, chunks_a, self.manager.team_a, "A")
        await interaction.response.send_message("【🔵 チームA】使用する指導者をリストから選んでください:", view=view, ephemeral=True)

    @discord.ui.button(label="🔵 A: 選択状況の確認", style=discord.ButtonStyle.secondary, row=0)
    async def btn_chk_a(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.manager.team_a and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("チームAのメンバーのみ確認可能です。", ephemeral=True)
        text = "**🔵 チームA メンバーの選択状況**\n" + self.format_team_status(self.manager.team_a)
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="🔴 B: 指導者をピックする", style=discord.ButtonStyle.danger, row=1)
    async def btn_pick_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.manager.team_b:
            return await interaction.response.send_message("あなたはチームBではありません。", ephemeral=True)
            
        data = self.manager.picks.get(interaction.user.id, {})
        if data.get("confirmed"):
            return await interaction.response.send_message("既に確定済みです！", ephemeral=True)
            
        survivors = self.manager.survivors
        half_idx = (len(survivors) + 1) // 2
        list_b = survivors[half_idx:]
        chunks_b = [list_b[i:i + 25] for i in range(0, len(list_b), 25)]
        
        view = PickLeaderView(self.manager, chunks_b, self.manager.team_b, "B")
        await interaction.response.send_message("【🔴 チームB】使用する指導者をリストから選んでください:", view=view, ephemeral=True)

    @discord.ui.button(label="🔴 B: 選択状況の確認", style=discord.ButtonStyle.secondary, row=1)
    async def btn_chk_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.manager.team_b and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("チームBのメンバーのみ確認可能です。", ephemeral=True)
        text = "**🔴 チームB メンバーの選択状況**\n" + self.format_team_status(self.manager.team_b)
        await interaction.response.send_message(text, ephemeral=True)

async def start_pick_phase(interaction, host, team_a, team_b, survivors, all_leaders, banned_global, banned_a, banned_b, sheet_manager, chosen_map=None, max_vote_val=0, match_id=None):
    manager = PickPhaseManager(interaction, host, team_a, team_b, survivors, all_leaders, banned_global, banned_a, banned_b, sheet_manager, chosen_map, max_vote_val, match_id)
    view = PickEntryView(manager)
    
    embed = discord.Embed(
        title="【指導者ピック】",
        description=f"終了時刻: <t:{manager.end_time}:R>\n各プレイヤーは操作ボタンから使用する指導者を仮選択し、確定してください。\n*(※確定後は変更できません)*",
        color=discord.Color.green()
    )
    
    embed.add_field(name="🌐 確定したメインBAN", value=format_leader_list(banned_global, all_leaders), inline=False)
    
    list_a, list_b = split_and_number_leaders(survivors, 'final_disp_no')
    
    def add_team_fields(target_embed, team_label, leader_list):
        chunk_size = 20
        chunks = [leader_list[i:i+chunk_size] for i in range(0, len(leader_list), chunk_size)]
        total_pages = max(1, len(chunks))
        for i, chunk in enumerate(chunks, 1):
            names = []
            for L in chunk:
                emoji = L.get('emoji_text', '')
                name = L['clean_name']
                disp_no = L.get('final_disp_no', 0)
                names.append(f"{disp_no}. {emoji} {name}" if emoji else f"{disp_no}. {name}")
            
            val = "\n".join(names) if names else "なし"
            page_title = f"{team_label} - {i}/{total_pages}" if total_pages > 1 else team_label
            target_embed.add_field(name=page_title, value=val, inline=True)

    add_team_fields(embed, "🔵 チームA ピック候補", list_a)
    add_team_fields(embed, "🔴 チームB ピック候補", list_b)
    
    try:
        if interaction.message:
            await interaction.message.edit(content=None, embed=embed, view=view)
            msg = interaction.message
        else:
            await interaction.edit_original_response(content=None, embed=embed, view=view)
            msg = await interaction.original_response()
    except Exception as e:
        logger.warning(f"メッセージの直接編集に失敗したため、新規送信でフォールバックします: {e}")
        msg = await interaction.channel.send(content=None, embed=embed, view=view)
        
    manager.start_timer(msg)