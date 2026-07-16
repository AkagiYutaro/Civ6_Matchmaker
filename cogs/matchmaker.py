import discord
from discord import app_commands
from discord.ext import commands
from ui.matchmaker_ui import MatchmakerPublicView, HostControlView

class MatchmakerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="civ_match", description="Civ6マルチプレイの参加登録とチーム分けを開始します。")
    @app_commands.describe(target_role="募集を通知（メンション）するロールを選択（任意）")
    async def civ_match(self, interaction: discord.Interaction, target_role: discord.Role = None):
        host = interaction.user
        
        # ロールが指定された場合はメンション文字列を作成
        mention_str = target_role.mention if target_role else ""
        
        # 1. 全員に見える公開用募集メッセージ（参加・辞退ボタンのみ）
        desc = f"{mention_str}\n\nホスト <@{host.id}> が募集を開始しました！\n以下のボタンから「参加」または「辞退」を表明してください。" if mention_str else f"ホスト <@{host.id}> が募集を開始しました！\n以下のボタンから「参加」または「辞退」を表明してください。"
        
        embed = discord.Embed(
            title="対戦募集",
            description=desc,
            color=discord.Color.blurple()
        )
        embed.add_field(name="参加者一覧 (1名)", value=f"・<@{host.id}>", inline=False)
        
        public_view = MatchmakerPublicView(host=host, sheet_manager=self.bot.sheet_manager)
        
        # メンションがある場合とない場合で送信方法を分ける
        if mention_str:
            await interaction.response.send_message(content=mention_str, embed=embed, view=public_view)
        else:
            await interaction.response.send_message(embed=embed, view=public_view)
            
        public_msg = await interaction.original_response()
        
        # 2. ホスト専用のコントロールパネルを追撃送信（ホストにしか見えない）
        control_view = HostControlView(
            public_message=public_msg, 
            public_view=public_view, 
            host=host, 
            sheet_manager=self.bot.sheet_manager
        )
        await interaction.followup.send(
            content="【👑 ホスト・管理者専用操作パネル】\n参加者が集まったら、下のボタンからチーム分けを実行してください。\n*(※このメッセージはあなたにしか見えていません)*",
            view=control_view,
            ephemeral=True
        )

async def setup(bot):
    await bot.add_cog(MatchmakerCog(bot))