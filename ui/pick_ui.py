import discord
import logging
from logic.pick_logic import PickPhaseManager

logger = logging.getLogger('discord.pick_ui')

class PickSelect(discord.ui.Select):
    def __init__(self, options, placeholder):
        super().__init__(placeholder=placeholder, min_values=0, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        uid = self.values[0] if self.values else None
        
        if uid:
            self.view.manager.picks[interaction.user.id] = {"leader": uid, "confirmed": False}
            self.view.selected_uid = uid
            
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
    from logic.banpick_logic import split_and_number_leaders, format_leader_list
    import random
    
    manager = PickPhaseManager(interaction, host, team_a, team_b, survivors, all_leaders, banned_global, banned_a, banned_b, sheet_manager)
    view = PickEntryView(manager)
    
    # 💡 修正: 新しいフェーズも進行中の色(Green)で、1つのメッセージを上書きする
    embed = discord.Embed(
        title="【フェーズ3: 指導者ピック】",
        description=f"終了時刻: <t:{manager.end_time}:R>\n各プレイヤーは操作ボタンから使用する指導者を仮選択し、確定してください。\n*(※確定後は変更できません)*",
        color=discord.Color.green()
    )
    
    embed.add_field(name="🌐 確定したメインBAN", value=format_leader_list(banned_global, all_leaders), inline=False)
    
    random.shuffle(survivors)
    list_a, list_b = split_and_number_leaders(survivors, 'final_disp_no')
    
    def add_draft_fields(target_embed, leader_list):
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
            page_title = f"ドラフト - {i}/{total_pages}"
            target_embed.add_field(name=page_title, value=val, inline=True)

    team_a_players = " ".join([f"<@{uid}>" for uid in team_a]) if team_a else "なし"
    embed.add_field(name="🔵 チームA プレイヤー", value=team_a_players, inline=False)
    add_draft_fields(embed, list_a)
    
    team_b_players = " ".join([f"<@{uid}>" for uid in team_b]) if team_b else "なし"
    embed.add_field(name="🔴 チームB プレイヤー", value=team_b_players, inline=False)
    add_draft_fields(embed, list_b)
    
    try:
        await interaction.edit_original_response(content=None, embed=embed, view=view)
        entry_message = await interaction.original_response()
    except Exception:
        # 万が一15分制限等でエラーになった時の保険
        entry_message = await interaction.channel.send(embed=embed, view=view)
        
    manager.start_timer(entry_message)