import discord
import logging

logger = logging.getLogger('discord.status_ui')

class StatusCheckButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.primary, label="📊 戦績", custom_id="civ_check_status_btn")

    async def callback(self, interaction: discord.Interaction):
        # 💡 自分にしか見えない(Ephemeral)状態で処理を開始
        await interaction.response.defer(ephemeral=True)
        
        sheet_manager = self.view.sheet_manager
        user_id = interaction.user.id
        
        # 集計シートから自分のデータを取得
        stats = sheet_manager.get_player_summary_stats(user_id)
        
        if not stats:
            return await interaction.followup.send("⚠️ まだあなたの戦績データが「集計」シートにありません。\n対戦を1回以上記録してから再度お試しください！", ephemeral=True)
            
        # 💡 追加: プレイヤーデータから現在のレートを取得
        rates_data = sheet_manager.get_player_rates([user_id])
        current_rate = rates_data.get(user_id, 1500)
        
        # ステータス表示用のリッチなEmbedを作成
        embed = discord.Embed(
            title=f"📊 {stats.get('プレイヤー名', interaction.user.display_name)} の戦績",
            color=discord.Color.gold()
        )
        
        # 1. 総合戦績
        win = stats.get("WIN", 0)
        lose = stats.get("LOSE", 0)
        win_rate = stats.get("WinRate", "0%")
        # 勝率が数値(float)で返ってきた場合はパーセント表記に変換
        if isinstance(win_rate, float):
            win_rate = f"{win_rate:.1%}"
        total = stats.get("総プレイ数", 0)
        
        # 💡 総合戦績の先頭にレートを表示
        embed.add_field(
            name="⚔️ 総合戦績", 
            value=f"**🎖️ レート: {current_rate}**\n**{win}勝 {lose}敗** (勝率: {win_rate})\n総プレイ数: {total}回", 
            inline=False
        )
        
        # 2. ランキングリストを綺麗にフォーマットする関数
        def get_list_str(prefix, count):
            items = [str(stats.get(f"{prefix}#{i}", "")).strip() for i in range(1, count + 1)]
            # 空白やハイフン("-")を除外
            valid_items = [item for item in items if item and item != "-"]
            if not valid_items:
                return "データなし"
            return "\n".join([f"{i}. {item}" for i, item in enumerate(valid_items, 1)])
        
        # 3. 各ランキングの追加
        picks_str = get_list_str("Pick", 5)
        embed.add_field(name="👑 指導者", value=picks_str, inline=False)
        
        team_str = get_list_str("Teammates", 6)
        embed.add_field(name="🤝 Teams", value=team_str, inline=False)
        
        rival_str = get_list_str("Rivals", 6)
        embed.add_field(name="🔥 Rivals", value=rival_str, inline=False)
        
        # 💡 エフェメラル(自分にだけ見える)で結果を送信
        await interaction.followup.send(embed=embed, ephemeral=True)


class PlayerStatusPanelView(discord.ui.View):
    def __init__(self, sheet_manager):
        super().__init__(timeout=None)
        self.sheet_manager = sheet_manager
        self.add_item(StatusCheckButton())