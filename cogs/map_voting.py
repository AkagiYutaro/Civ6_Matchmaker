import discord

class MapVoteSelect(discord.ui.Select):
    """マップを仮選択するためのドロップダウンメニュー"""
    def __init__(self, map_emojis: dict, parent_view):
        self.parent_view = parent_view
        options = []
        for name, emoji in map_emojis.items():
            options.append(discord.SelectOption(label=name, emoji=emoji, value=name))
        
        super().__init__(
            placeholder="🗺️ マップをリストから選択...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="civ_map_vote_select"
        )

    async def callback(self, interaction: discord.Interaction):
        # ユーザーが何を選択したかを一時保存（この段階ではまだ未確定）
        selected_map = self.values[0]
        self.parent_view.temp_selection = selected_map
        
        # 確定ボタンを有効化して、状態を更新
        self.parent_view.confirm_button.disabled = False
        
        await interaction.response.edit_message(
            content=f"> 🗺️ **{selected_map}** を仮選択中です...\n"
                    "> **【🗳️ 投票】** ボタンを押して確定してください",
            view=self.parent_view
        )


class ConfirmVoteButton(discord.ui.Button):
    """仮選択したマップを正式に投票確定させるためのアイコンボタン"""
    def __init__(self, parent_view):
        super().__init__(
            label="投票",
            style=discord.ButtonStyle.success,
            emoji="🗳️", # 備考にあったアイコンの設定
            custom_id="civ_confirm_vote_btn",
            disabled=True # 最初はマップが選ばれていないので無効化
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        selected_map = self.parent_view.temp_selection

        if not selected_map:
            await interaction.response.send_message("⚠️ マップが選択されていません。", ephemeral=True)
            return

        # matchmaker.py 側の専用メソッド経由で安全に登録
        await self.parent_view.main_matchmaker_view.register_vote(
            interaction=interaction,
            user_id=user_id,
            map_name=selected_map
        )

        # 自身のビューのパーツを無効化（二重操作防止）
        for item in self.parent_view.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=f"✅ **{selected_map}** に投票しました！\n"
                    "*(現在の投票内容はチーム分けが行われるまで非公開です)*",
            view=None
        )


class MapVoteView(discord.ui.View):
    """仮選択と確定ボタンをセットにした本人専用(ephemeral)の投票用UI"""
    def __init__(self, map_emojis: dict, main_matchmaker_view):
        super().__init__(timeout=300) # 5分で自動タイムアウト
        self.main_matchmaker_view = main_matchmaker_view
        self.temp_selection = None

        # ドロップダウンを追加
        self.select_menu = MapVoteSelect(map_emojis, self)
        self.add_item(self.select_menu)

        # 確定ボタンを追加
        self.confirm_button = ConfirmVoteButton(self)
        self.add_item(self.confirm_button)