import discord
import logging

logger = logging.getLogger('discord.registration_ui')

# ==========================================
# カテゴリ別ドロップダウン (エフェメラル用)
# ==========================================
class CategorySelect(discord.ui.Select):
    def __init__(self, title, options_data):
        self.category_title = title
        
        opts = []
        for d in options_data:
            desc = d["備考"][:100]
            opts.append(discord.SelectOption(
                label=d["条件"][:100],
                description=desc if desc else None,
                value=str(d.get("CivNO", d["条件"])) 
            ))
            
        super().__init__(
            placeholder=f"▼ {title}"[:150],
            min_values=1,
            max_values=1, 
            options=opts,
            custom_id=f"civ_reg_select_{title[:50]}"
        )

    async def callback(self, interaction: discord.Interaction):
        # 選択された内容を親Viewに記録
        self.view.selections[self.category_title] = self.values[0]
        # 回答状況メッセージを更新
        await self.view.update_status(interaction)

class ConfirmRegistrationButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.success, label="登録する", custom_id="civ_confirm_registration", disabled=True)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view = self.view
        user_id = interaction.user.id
        player_name = interaction.user.display_name
        
        active_flgs = list(view.selections.values())
        
        try:
            success = view.sheet_manager.register_or_update_player(
                discord_id=user_id,
                player_name=player_name,
                active_flgs=active_flgs
            )
            
            if success:
                # ユーザーへの結果報告用に、選んだ条件のラベルを抽出
                selected_labels = []
                for title, civ_no in view.selections.items():
                    for opt in view.categories[title]:
                        if str(opt.get("CivNO", opt["条件"])) == str(civ_no):
                            selected_labels.append(f"{title} : {opt['条件']}")
                            break
                            
                items_str = '\n・'.join(selected_labels) if selected_labels else 'なし'
                msg = f"🎉 **プレイヤー登録が完了しました！**\n\n**【登録内容】**\n・{items_str}\n\n※以降、内容の変更が必要な場合は管理者へお問い合わせください。"
                
                # 💡 要件③: 登録完了後はフォームを消す (view=None)
                await interaction.edit_original_response(content=msg, view=None)
            else:
                await interaction.edit_original_response(content="❌ 登録に失敗しました。スプレッドシートへの接続を確認してください。", view=None)
        except Exception as e:
            logger.error(f"登録エラー: {e}")
            await interaction.edit_original_response(content=f"❌ 予期せぬエラーが発生しました: {e}", view=None)

class RegistrationFormView(discord.ui.View):
    def __init__(self, sheet_manager, categories):
        super().__init__(timeout=900)
        self.sheet_manager = sheet_manager
        self.categories = categories
        self.selections = {} 
        
        for title, options in categories.items():
            self.add_item(CategorySelect(title, options))
            
        self.confirm_btn = ConfirmRegistrationButton()
        self.add_item(self.confirm_btn)

    async def update_status(self, interaction: discord.Interaction):
        status_lines = []
        all_selected = True
        
        for title in self.categories.keys():
            if title in self.selections:
                civ_no = self.selections[title]
                selected_label = "選択済み"
                # CivNOから選択したラベル名(条件)を検索して取得
                for opt in self.categories[title]:
                    if str(opt.get("CivNO", opt["条件"])) == str(civ_no):
                        selected_label = opt["条件"]
                        break
                # 💡 要件②: 選択状況を「タイトル : 選択内容」の形式で表示
                status_lines.append(f"✅ **{title}** : {selected_label}")
            else:
                status_lines.append(f"⬜ **{title}** : 未選択")
                all_selected = False
                
        self.confirm_btn.disabled = not all_selected
        
        status_text = "> **【現在の回答状況】**\n> " + "\n> ".join(status_lines)
        if all_selected:
            status_text += "\n\n🎉 **すべて回答しました！下の「登録する」ボタンを押してください。**"
        else:
            status_text += "\n\n⚠️ **すべてのメニューから当てはまる項目を選んでください。**"
            
        await interaction.response.edit_message(content=status_text, view=self)


# ==========================================
# 常設用パネル (チャンネルに配置される大元のView)
# ==========================================
class RegistrationPanelView(discord.ui.View):
    def __init__(self, sheet_manager):
        super().__init__(timeout=None)
        self.sheet_manager = sheet_manager

    @discord.ui.button(label="📝 プレイヤー登録", style=discord.ButtonStyle.primary, custom_id="civ_start_registration")
    async def start_registration(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            # 💡 要件①: すでにスプレッドシートに登録済みか確認
            scores = self.sheet_manager.get_player_scores([interaction.user.id])
            if scores.get(interaction.user.id) is not None:
                return await interaction.followup.send(
                    "❌ **すでに登録済みです。**\n登録内容の修正・変更が必要な場合は、管理者へお問い合わせください。", 
                    ephemeral=True
                )

            categories = self.sheet_manager.get_master_categories()
            
            if not categories:
                return await interaction.followup.send("❌ 質問項目が設定されていません。スプレッドシートの「マスタ設定」を確認してください。", ephemeral=True)
                
            form_view = RegistrationFormView(self.sheet_manager, categories)
            
            status_lines = [f"⬜ **{title}** : 未選択" for title in categories.keys()]
            initial_text = "> **【現在の回答状況】**\n> " + "\n> ".join(status_lines) + "\n\n⚠️ **すべてのメニューから当てはまる項目を選んでください。**"
            
            await interaction.followup.send(
                content=initial_text,
                view=form_view,
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"アンケート開始エラー: {e}")
            await interaction.followup.send(f"エラーが発生しました: {e}", ephemeral=True)