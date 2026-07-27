import discord

class RateCheckButton(discord.ui.Button):
    def __init__(self, rate_results: dict):
        super().__init__(style=discord.ButtonStyle.secondary, label="📊 自分のレート変動を確認", custom_id="check_rate")
        self.rate_results = rate_results

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if user_id not in self.rate_results:
            return await interaction.response.send_message("あなたは今回の対戦メンバーに含まれていません。", ephemeral=True)
            
        data = self.rate_results[user_id]
        diff = data['diff']
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        
        embed = discord.Embed(
            title="📊 あなたのレート変動",
            description=f"**{data['old']}** ➔ **{data['new']}** ({diff_str})",
            color=discord.Color.green() if diff >= 0 else discord.Color.red()
        )
        # 本人にだけ(ephemeral)結果を表示する
        await interaction.response.send_message(embed=embed, ephemeral=True)

class RateCheckView(discord.ui.View):
    def __init__(self, rate_results: dict):
        super().__init__(timeout=None)
        self.add_item(RateCheckButton(rate_results))