import discord
from discord import app_commands
from discord.ext import commands
import re
import random
from ui.matchmaker_ui import MatchmakerPublicView, HostControlView, MAP_EMOJIS
from logic.matchmaker_logic import calculate_map_votes
from ui.banpick_ui import BanPickStartView

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

    # 💡 追加: メニューを消してしまった場合などの強制移行コマンド
    @app_commands.command(name="map_vote", description="[管理/ホスト用] 誤って操作パネルを消してしまった場合、強制的にマップを決定しBAN/PICKへ移行します。")
    @app_commands.describe(map_name="強制決定するマップ名を選択（任意）")
    async def map_vote(self, interaction: discord.Interaction, map_name: str = None):
        is_admin = interaction.user.guild_permissions.administrator
        
        # 直近のBotの発言から「チーム分け結果」のメッセージを探し出す
        bot_msg = None
        async for msg in interaction.channel.history(limit=20):
            if msg.author == self.bot.user and msg.embeds:
                if "チーム分け結果" in str(msg.embeds[0].title):
                    bot_msg = msg
                    break
        
        if not bot_msg:
            return await interaction.response.send_message("直近にチーム分け結果のメッセージが見つかりませんでした。最初からやり直してください。", ephemeral=True)
            
        # Embedのテキストからメンション部分を抽出し、チームメンバーのIDを復元する
        team_a = []
        team_b = []
        for field in bot_msg.embeds[0].fields:
            if "チームA" in field.name:
                team_a = [int(i) for i in re.findall(r'<@!?(\d+)>', field.value)]
            elif "チームB" in field.name:
                team_b = [int(i) for i in re.findall(r'<@!?(\d+)>', field.value)]
                
        if not team_a and not team_b:
            return await interaction.response.send_message("メッセージからチーム情報が抽出できませんでした。", ephemeral=True)
            
        if not is_admin and interaction.user.id not in (team_a + team_b):
            return await interaction.response.send_message("対戦の参加者または管理者のみ実行可能です。", ephemeral=True)

        chosen_map = map_name
        max_votes = 0
        if not chosen_map:
            if hasattr(self.bot, 'match_sessions') and bot_msg.id in self.bot.match_sessions:
                result_view = self.bot.match_sessions[bot_msg.id]
                from logic.matchmaker_logic import calculate_map_votes
                from ui.matchmaker_ui import MAP_EMOJIS
                calc_map, max_votes = calculate_map_votes(result_view.map_votes_data, result_view.participants, MAP_EMOJIS)
                if max_votes > 0:
                    chosen_map = calc_map
                    
        # 投票データも指定もなく未定の場合はランダム
        if not chosen_map:
            import random
            MAPS = ["七つの海", "パンゲア", "パンゲアウルティマ", "湖", "ハイランド", "豊かな台地", "群島", "地軸傾斜"]
            chosen_map = random.choice(MAPS)
        
        from ui.banpick_ui import BanPickStartView
        bp_view = BanPickStartView(
            host=interaction.user,
            team_a=team_a,
            team_b=team_b,
            sheet_manager=self.bot.sheet_manager,
            chosen_map=chosen_map,
            max_vote_val=max_votes
        )
        
        # 💡 新規メッセージを送るのではなく、見つけ出した大元メッセージ(bot_msg)を上書きする
        embed = bot_msg.embeds[0]
        map_result_str = f"🗺️ Map: **{chosen_map}** （{max_votes}票獲得）" if max_votes > 0 else f"🗺️ Map: **{chosen_map}** (強制決定)"
        embed.set_field_at(0, name="【対戦設定】", value=map_result_str, inline=False)
        
        await bot_msg.edit(
            content=f"🗺️ マップを強制決定しました。ホストは以下のボタンからBAN/PICKを開始してください。",
            embed=embed,
            view=bp_view
        )
        
        await interaction.response.send_message("✅ 元の募集メッセージを更新し、BAN/PICKフェーズへ強制移行しました。", ephemeral=True)
        
        if max_votes > 0:
            await interaction.followup.send(f"📊 投票データから **{chosen_map}** が選出されました（{max_votes}票獲得）。", ephemeral=True)

    @app_commands.command(name="scrap", description="[管理/ホスト用] 進行中のマッチングやBAN/PICKセッションを破棄して中止します。")
    async def scrap(self, interaction: discord.Interaction):
        is_admin = interaction.user.guild_permissions.administrator
        
        target_msg = None
        async for msg in interaction.channel.history(limit=20):
            if msg.author == self.bot.user and msg.embeds:
                if any(k in str(msg.embeds[0].title) for k in ["募集", "チーム分け", "BAN", "指導者ピック"]):
                    target_msg = msg
                    break
                    
        if not target_msg:
            return await interaction.response.send_message("破棄可能な進行中メッセージが直近に見つかりませんでした。", ephemeral=True)
            
        try:
            embed = discord.Embed(title="🚫 この対戦セッションは破棄されました。", color=discord.Color.dark_grey())
            await target_msg.edit(content=None, embed=embed, view=None)
            
            if hasattr(self.bot, 'match_sessions') and target_msg.id in self.bot.match_sessions:
                del self.bot.match_sessions[target_msg.id]
                
            await interaction.response.send_message("✅ 対戦セッションを破棄・リセットしました。", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"破棄に失敗しました: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(MatchmakerCog(bot))