import discord

class MapSelect(discord.ui.Select):
    def __init__(self, parent_view, map_list):
        # 辞書(MAP_EMOJIS)からドロップダウンの選択肢を作成
        options = [
            discord.SelectOption(label=name, value=name, emoji=emoji) 
            for name, emoji in map_list.items()
        ]
        super().__init__(
            placeholder="マップをリストから選択... ▼", 
            options=options, 
            min_values=1, 
            max_values=1
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        # ユーザーが選択したマップを一時保存
        selected_map = self.values[0]
        self.parent_view.temp_selection = selected_map
        
        # 確定ボタンを有効化してメッセージを更新
        self.parent_view.confirm_button.disabled = False
        await interaction.response.edit_message(
            content=f"> 🗺️ **{selected_map}** を仮選択中です...\n"
                    f"> **【🗳️ 投票】** ボタンを押して確定してください",
            view=self.parent_view
        )

class ConfirmVoteButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(label="🗳️ 投票", style=discord.ButtonStyle.success, disabled=True)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        selected = self.parent_view.temp_selection
        user_id = interaction.user.id
        
        # 親ビューのデータ保存領域に投票を記録
        self.parent_view.matchmaker_view.map_votes_data[user_id] = selected
        
        # パネルを消して完了メッセージにする
        await interaction.response.edit_message(
            content=f"✅ 🗺️ **{selected}** に投票を確定しました！\n*(※結果はチーム分け時に発表されます)*",
            view=None
        )

class MapVotingView(discord.ui.View):
    def __init__(self, matchmaker_view, map_list):
        super().__init__(timeout=300) # 5分でタイムアウト
        self.matchmaker_view = matchmaker_view
        self.temp_selection = None
        
        self.confirm_button = ConfirmVoteButton(self)
        self.add_item(MapSelect(self, map_list))
        self.add_item(self.confirm_button)