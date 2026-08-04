import discord
from discord.ext import commands
from discord import app_commands
from ui.status_ui import PlayerStatusPanelView
import logging

logger = logging.getLogger('discord.cogs.status')

class StatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="civ_setup_status", description="[管理者用] プレイヤーステータス確認パネルをチャンネルに設置します。")
    @app_commands.default_permissions(administrator=True) # 管理者権限を持つユーザーのみ実行可能
    async def civ_setup_status(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📊 プレイヤーステータス確認",
            description=(
                "自分のこれまでの戦績、よく使う指導者、よく一緒に遊ぶプレイヤーなどのデータを閲覧できます。\n\n"
                "下のボタンを押すとステータスが表示されます。"
            ),
            color=discord.Color.gold()
        )
        
        view = PlayerStatusPanelView(self.bot.sheet_manager)
        
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ ステータス確認パネルをこのチャンネルに設置しました。", ephemeral=True)

async def setup(bot):
    await bot.add_cog(StatusCog(bot))