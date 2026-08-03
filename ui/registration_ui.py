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
                value=str(d.get("CivNO", d["条件"])) # 💡 FLG名の代わりにCivNOを識別子として使う
            ))
            
        super().__init__(
            placeholder=f"▼ {title}"[:150],
            min_values=1,
            max_values=1, # 💡 ここを1に制限することで、カテゴリ内で複数選べないようにします
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
        
        # すべてのカテゴリから選択されたCivNOを1つのリストにまとめる
        active_flgs = list(view.selections.values())
        
        try:
            # スプレッドシートにデータを保存・更新 (レートもここで自動計算される)
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
                            selected_labels.append(opt["条件"])
                            break
                            
                items_str = '\n・'.join(selected_labels) if selected_labels else 'なし'
                msg = f"🎉 **登録・更新が完了しました！**\n\n**【登録内容】**\n・{items_str}"
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.followup.send("❌ 登録に失敗しました。スプレッドシートへの接続を確認してください。", ephemeral=True)
        except Exception as e:
            logger.error(f"登録エラー: {e}")
            await interaction.followup.send(f"❌ 予期せぬエラーが発生しました: {e}", ephemeral=True)

class RegistrationFormView(discord.ui.View):
    def __init__(self, sheet_manager, categories):
        super().__init__(timeout=900)
        self.sheet_manager = sheet_manager
        self.categories = categories
        self.selections = {} # どのカテゴリで何を選んだかを保持
        
        # 💡 カテゴリごとに1つずつドロップダウンメニューを追加 (最大5個まで)
        for title, options in categories.items():
            self.add_item(CategorySelect(title, options))
            
        self.confirm_btn = ConfirmRegistrationButton()
        self.add_item(self.confirm_btn)

    async def update_status(self, interaction: discord.Interaction):
        # 💡 要件③: 現在の入力状況をメッセージで案内する
        status_lines = []
        all_selected = True
        
        for title in self.categories.keys():
            if title in self.selections:
                status_lines.append(f"✅ **{title}** : 選択済み")
            else:
                status_lines.append(f"⬜ **{title}** : 未選択")
                all_selected = False
                
        # すべて回答されたら登録ボタンを有効化
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
        super().__init__(timeout=None) # 常設するためタイムアウトなし
        self.sheet_manager = sheet_manager

    # 💡 要件①: ボタン名を変更
    @discord.ui.button(label="📝 プレイヤー登録", style=discord.ButtonStyle.primary, custom_id="civ_start_registration")
    async def start_registration(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            # スプレッドシートからカテゴリ(タイトル)ごとにまとめたマスタデータを取得
            categories = self.sheet_manager.get_master_categories()
            
            if not categories:
                return await interaction.followup.send("❌ 質問項目が設定されていません。スプレッドシートの「マスタ設定」を確認してください。", ephemeral=True)
                
            form_view = RegistrationFormView(self.sheet_manager, categories)
            
            # 初期状態の案内テキストを作成
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