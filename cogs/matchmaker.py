import discord
from discord import app_commands
from discord.ext import commands
import re
import random
import logging

from ui.matchmaker_ui import MatchmakerPublicView, HostControlView, HostMapControlView, TeamResultPublicView, MAP_EMOJIS
from logic.matchmaker_logic import calculate_map_votes, balance_teams
from ui.banpick_ui import BanPickStartView
from ui.registration_ui import RegistrationPanelView
from ui.status_ui import PlayerStatusPanelView

logger = logging.getLogger('discord.cogs.matchmaker')

class MatchmakerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """全ての操作（コマンド実行やボタンクリック）を記録し、連打の原因を特定するためのログ出力"""
        user = interaction.user
        # スラッシュコマンドの実行ログ
        if interaction.type == discord.InteractionType.application_command:
            cmd_name = interaction.command.name if interaction.command else "Unknown"
            logger.info(f"[ACTION-CMD] {user.display_name} ({user.name}) executed: /{cmd_name}")
        # ボタンやドロップダウンの操作ログ
        elif interaction.type == discord.InteractionType.component:
            custom_id = interaction.data.get('custom_id', 'Unknown')
            logger.info(f"[ACTION-BTN] {user.display_name} ({user.name}) clicked: {custom_id}")

    @app_commands.command(name="civ_setup_register", description="[管理者用] プレイヤーのスキル登録・アンケートパネルをチャンネルに設置します。")
    @app_commands.default_permissions(administrator=True)
    async def civ_setup_register(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📊 プレイヤー登録",
            description=(
                "マルチプレイに参加するには、事前のプレイヤー登録が必要です。\n"
                "下のボタンから登録してください。"
            ),
            color=discord.Color.green()
        )
        
        view = RegistrationPanelView(self.bot.sheet_manager)
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ 登録パネルをこのチャンネルに設置しました。", ephemeral=True)

    @app_commands.command(name="civ_setup_status", description="[管理者用] プレイヤーステータス確認パネルをチャンネルに設置します。")
    @app_commands.default_permissions(administrator=True)
    async def civ_setup_status(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📊 戦績確認",
            description=(
                "自分のこれまでの戦績などのデータを閲覧できます。\n\n"
                "下のボタンを押すと**戦績**が表示されます。"
            ),
            color=discord.Color.gold()
        )
        
        view = PlayerStatusPanelView(self.bot.sheet_manager)
        
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ ステータス確認パネルをこのチャンネルに設置しました。", ephemeral=True)

    @app_commands.command(name="civ_match", description="Civ6マルチプレイの参加登録とチーム分けを開始します。")
    @app_commands.describe(target_role="募集を通知（メンション）するロールを選択（任意）")
    async def civ_match(self, interaction: discord.Interaction, target_role: discord.Role = None):
        host = interaction.user
        
        # ロールが指定された場合はメンション文字列を作成
        mention_str = target_role.mention if target_role else ""
        
        # 1. 全員に見える公開用募集メッセージ（参加・辞退ボタンのみ）
        desc = f"{mention_str}\n\nホスト <@{host.id}> が募集を開始しました！\n以下のボタンから「参加」または「辞退」を表明してください。" if mention_str else f"ホスト <@{host.id}> が募集を開始しました！\n以下のボタンから「参加」または「辞退」を表明してください。"
        
        # スプレッドシートから次の対戦IDを取得
        match_id = self.bot.sheet_manager.get_next_match_id()
        
        # 募集用メッセージの作成
        embed = discord.Embed(
            title=f"対戦募集 {match_id}",
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
            content="参加者が集まったら、下のボタンからチーム分けを実行してください。",
            view=control_view,
            ephemeral=True
        )

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
                calc_map, max_votes = calculate_map_votes(result_view.map_votes_data, result_view.participants, MAP_EMOJIS)
                if max_votes > 0:
                    chosen_map = calc_map
                    
        # 投票データも指定もなく未定の場合はランダム
        if not chosen_map:
            MAPS = ["七つの海", "パンゲア", "パンゲアウルティマ", "湖", "ハイランド", "豊かな台地", "群島", "地軸傾斜"]
            chosen_map = map_name if map_name else random.choice(MAPS)
        
        match_id = self.bot.sheet_manager.get_next_match_id()
        
        bp_view = BanPickStartView(
            host=interaction.user,
            team_a=team_a,
            team_b=team_b,
            sheet_manager=self.bot.sheet_manager,
            chosen_map=chosen_map,
            max_vote_val=max_votes,
            match_id=match_id
        )
        
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

    @app_commands.command(name="civ_force_split", description="[管理/ホスト用] 募集パネルが15分経過で応答しなくなった場合、強制的にチーム分けを実行します。")
    async def civ_force_split(self, interaction: discord.Interaction):
        is_admin = interaction.user.guild_permissions.administrator
        
        # 直近のBotの発言から「対戦募集」のメッセージを探し出す
        target_msg = None
        async for msg in interaction.channel.history(limit=50):
            if msg.author == self.bot.user and msg.embeds:
                if "対戦募集" in str(msg.embeds[0].title) or "参加者一覧" in str(msg.embeds[0].fields[0].name):
                    target_msg = msg
                    break
        
        if not target_msg:
            return await interaction.response.send_message("直近に募集メッセージが見つかりませんでした。再度 /civ_match を実行してください。", ephemeral=True)
            
        # Embedのテキストからメンション部分を抽出し、参加者のIDを復元する
        participants = {}
        for field in target_msg.embeds[0].fields:
            if "参加者一覧" in field.name:
                # 正規表現で <@12345...> を抽出
                extracted_ids = re.findall(r'<@!?(\d+)>', field.value)
                for pid in extracted_ids:
                    participants[int(pid)] = f"ID:{pid}"
                    
        if len(participants) < 2:
            return await interaction.response.send_message(f"参加者が2名未満（現在{len(participants)}名）のためチーム分けできません。", ephemeral=True)
            
        if not is_admin and interaction.user.id not in participants:
            return await interaction.response.send_message("対戦の参加者または管理者のみ実行可能です。", ephemeral=True)

        # 処理時間がかかる可能性があるため待機状態にする
        await interaction.response.defer()

        # 抽出したメンバーでチーム分け処理
        players_info = self.bot.sheet_manager.get_player_scores(list(participants.keys()))
        for p_id, p_data in list(players_info.items()):
            if p_data is None:
                players_info[p_id] = {"name": f"未登録({str(p_id)[:5]})", "score": 3}

        team_a, team_b = balance_teams(players_info)
        
        team_a_str = "\n".join([f"・<@{p_id}>" for p_id in team_a]) if team_a else "なし"
        team_b_str = "\n".join([f"・<@{p_id}>" for p_id in team_b]) if team_b else "なし"
        
        host = interaction.user
        result_public_view = TeamResultPublicView(participants, host)
        result_public_view.team_a_ids = team_a
        result_public_view.team_b_ids = team_b
        
        match_id = self.bot.sheet_manager.get_next_match_id()

        embed = discord.Embed(title=f"対戦募集 {match_id}", description="**チーム分け結果 (コマンド強制実行)**", color=discord.Color.gold())
        embed.add_field(name="【対戦設定】", value="🗺️ Map: **未定（現在メンバー投票中...）**", inline=False)
        embed.add_field(name="🔵 チームA", value=team_a_str, inline=True)
        embed.add_field(name="🔴 チームB", value=team_b_str, inline=True)

        # 古い募集メッセージを無効化して混乱を防ぐ
        try:
            old_embed = target_msg.embeds[0]
            old_embed.color = discord.Color.dark_grey()
            await target_msg.edit(content="⚠️ この募集パネルは時間経過により強制移行されました。", embed=old_embed, view=None)
        except:
            pass

        # チーム分け結果パネルを通常メッセージとして新しく送信
        new_public_msg = await interaction.channel.send(embed=embed, view=result_public_view)
        
        # コマンドを実行したホストに対して、新しくマップ開票用の操作パネルを発行
        next_control_view = HostMapControlView(new_public_msg, result_public_view, host, self.bot.sheet_manager)
        await interaction.followup.send(
            content="✅ **チーム分けを強制実行しました！**\nメンバーのマップ投票を集計するため、タイミングを見て「マップ開票・決定」を押してください。",
            view=next_control_view,
            ephemeral=True
        )

async def setup(bot):
    await bot.add_cog(MatchmakerCog(bot))