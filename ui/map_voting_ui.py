import discord

class MapVoteSelect(discord.ui.Select):
    def __init__(self, parent_view, map_emojis: dict):
        self.parent_view = parent_view
        options = [
            discord.SelectOption(label=name, emoji=emoji, value=name)
            for name, emoji in map_emojis.items()
        ]
        super().__init__(
            placeholder="🗺️ マップをリストから選択...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="civ_map_vote_select"
        )

    async def callback(self, interaction: discord.Interaction):
        selected_map = self.values[0]
        self.parent_view.temp_selection = selected_map
        self.parent_view.confirm_button.disabled = False
        await interaction.response.edit_message(
            content=f"> 🗺️ **{selected_map}** を仮選択中です...\n"
                    "> **【🗳️ 投票を確定】** ボタンを押してください",
            view=self.parent_view
        )

class ConfirmVoteButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(
            label="投票を確定",
            style=discord.ButtonStyle.success,
            emoji="🗳️",
            custom_id="civ_confirm_vote_btn",
            disabled=True
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        selected_map = self.parent_view.temp_selection

        if not selected_map:
            return await interaction.response.send_message("⚠️ マップが選択されていません。", ephemeral=True)

        # 親パネル(TeamResultPublicView)に投票データを保存
        self.parent_view.public_view.map_votes_data[user_id] = selected_map

        for item in self.parent_view.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=f"✅ **{selected_map}** に投票しました！\n"
                    "*(ホストが開票すると結果に反映されます)*",
            view=None
        )

class MapVotingView(discord.ui.View):
    def __init__(self, public_view, map_emojis: dict):
        super().__init__(timeout=300)
        self.public_view = public_view
        self.temp_selection = None
        self.confirm_button = ConfirmVoteButton(self)
        
        self.add_item(MapVoteSelect(self, map_emojis))
        self.add_item(self.confirm_button)