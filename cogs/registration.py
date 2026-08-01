import discord
from discord.ext import commands
from discord import app_commands
from ui.registration_ui import RegistrationPanelView
import logging

logger = logging.getLogger('discord.cogs.registration')

class RegistrationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="civ_setup_register", description="[管理者用] プレイヤーのスキル登録・アンケートパネルをチャンネルに設置します。")
    @app_commands.default_permissions(administrator=True) # 管理者権限を持つユーザーのみ実行可能
    async def civ_setup_register(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📊 Civ6 プレイヤー登録・アンケート",
            description=(
                "チーム分けマルチプレイに参加するには、事前のプレイヤー登録が必要です。\n"
                "下のボタンからアンケートに回答してください。\n\n"
                "※回答結果に基づいて、チームの合計実力が均等になるよう自動調整されます。\n"
                "※すでに登録済みの方も、再度回答することで最新の情報に上書きできます。"
            ),
            color=discord.Color.green()
        )
        
        # sheet_manager を渡してViewを作成
        view = RegistrationPanelView(self.bot.sheet_manager)
        
        # パネルを通常メッセージとして送信
        await interaction.channel.send(embed=embed, view=view)
        
        # コマンドを実行した本人にだけ成功メッセージを返す
        await interaction.response.send_message("✅ 登録パネルをこのチャンネルに設置しました。", ephemeral=True)

async def setup(bot):
    await bot.add_cog(RegistrationCog(bot))