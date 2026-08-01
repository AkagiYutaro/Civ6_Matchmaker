import discord
import logging

logger = logging.getLogger('discord.registration_ui')

# ==========================================
# アンケート回答フォーム (エフェメラル用)
# ==========================================
class RegistrationSelect(discord.ui.Select):
    def __init__(self, flg_list):
        options = []
        for flg in flg_list:
            # ラベルと説明を設定（上限を超えないように文字数制限）
            desc = str(flg.get("description", ""))[:100]
            options.append(discord.SelectOption(
                label=str(flg.get("flg_name", ""))[:100],
                description=desc if desc else None,
                value=str(flg.get("flg_name", ""))[:100]
            ))
            
        super().__init__(
            placeholder="当てはまる項目をすべて選んでください",
            min_values=0,
            max_values=len(options),
            options=options,
            custom_id="civ_registration_select"
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_flgs = self.values
        await interaction.response.edit_message(
            content=f"✅ **{len(self.values)}** 個の項目を選択中です。\nよろしければ下の「登録する」ボタンを押してください。",
            view=self.view
        )

class ConfirmRegistrationButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.success, label="登録する", custom_id="civ_confirm_registration")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view = self.view
        user_id = interaction.user.id
        player_name = interaction.user.display_name
        
        try:
            # スプレッドシートにデータを保存・更新
            success = view.sheet_manager.register_or_update_player(
                discord_id=user_id,
                player_name=player_name,
                active_flgs=view.selected_flgs
            )
            
            if success:
                items_str = '\n・'.join(view.selected_flgs) if view.selected_flgs else 'なし'
                msg = f"🎉 **登録・更新が完了しました！**\n\n**【登録内容】**\n・{items_str}"
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.followup.send("❌ 登録に失敗しました。スプレッドシートへの接続を確認してください。", ephemeral=True)
        except Exception as e:
            logger.error(f"登録エラー: {e}")
            await interaction.followup.send(f"❌ 予期せぬエラーが発生しました: {e}", ephemeral=True)

class RegistrationFormView(discord.ui.View):
    def __init__(self, sheet_manager, flg_list):
        super().__init__(timeout=900)
        self.sheet_manager = sheet_manager
        self.selected_flgs = []
        self.add_item(RegistrationSelect(flg_list))
        self.add_item(ConfirmRegistrationButton())


# ==========================================
# 常設用パネル (チャンネルに配置される大元のView)
# ==========================================
class RegistrationPanelView(discord.ui.View):
    def __init__(self, sheet_manager):
        super().__init__(timeout=None) # 常設するためタイムアウトなし
        self.sheet_manager = sheet_manager

    @discord.ui.button(label="📝 スキルアンケートに回答する", style=discord.ButtonStyle.primary, custom_id="civ_start_registration")
    async def start_registration(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            # スプレッドシートから質問項目をリアルタイム取得
            flg_list = self.sheet_manager.get_master_flgs()
            
            if not flg_list:
                return await interaction.followup.send("❌ 質問項目が設定されていません。スプレッドシートの「マスタ設定」を確認してください。", ephemeral=True)
                
            form_view = RegistrationFormView(self.sheet_manager, flg_list)
            await interaction.followup.send(
                "> **【Civ6 プレイヤーアンケート】**\n> あなたのプレイスタイルや経験について教えてください。\n> 当てはまる項目をドロップダウンから選択し、登録ボタンを押してください。",
                view=form_view,
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"アンケート開始エラー: {e}")
            await interaction.followup.send(f"エラーが発生しました: {e}", ephemeral=True)