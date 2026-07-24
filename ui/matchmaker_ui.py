import discord
import datetime

# 💡 JST（日本時間）の定義を追加
JST = datetime.timezone(datetime.timedelta(hours=9))

from logic.matchmaker_logic import balance_teams, calculate_map_votes
from ui.map_voting_ui import MapVotingView
from ui.banpick_ui import BanPickStartView # 💡 BAN/PICKへの移行用にインポート

MAP_EMOJIS = {
    "七つの海": "7️⃣",
    "パンゲア": "🇵",
    "パンゲアウルティマ": "🇺",
    "湖": "🇱",
    "ハイランド": "🐴",
    "豊かな台地": "🌳",
    "群島": "🏝️",
    "地軸傾斜": "🏹"
}

# ==========================================
# 1. 募集フェーズの公開用パネル (参加・辞退のみ)
# ==========================================
class MatchmakerPublicView(discord.ui.View):
    def __init__(self, host, sheet_manager):
        super().__init__(timeout=None)
        self.host = host
        self.sheet_manager = sheet_manager
        self.participants = {host.id: host.display_name}
        
    async def update_embed(self, interaction: discord.Interaction):
        embed = interaction.message.embeds[0]
        member_list_str = "\n".join([f"・<@{p_id}>" for p_id in self.participants.keys()]) if self.participants else "現在参加者なし"
        embed.set_field_at(0, name=f"参加者一覧 ({len(self.participants)}名)", value=member_list_str, inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="参加", style=discord.ButtonStyle.success, custom_id="civ_join_btn")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        try:
            players_info = self.sheet_manager.get_player_scores([user.id])
        except Exception as e:
            return await interaction.response.send_message(f"❌ **スプレッドシート接続エラー** ({e})", ephemeral=True)

        if players_info.get(user.id) is None:
            return await interaction.response.send_message("⚠️ **チーム分けのため事前にアンケートへの回答が必要です。**", ephemeral=True)

        if user.id not in self.participants:
            self.participants[user.id] = user.display_name
            await self.update_embed(interaction=interaction)
            await interaction.followup.send("✅ 参加登録しました！", ephemeral=True)
        else:
            await interaction.response.send_message("既に参加登録済みです！", ephemeral=True)

    @discord.ui.button(label="辞退", style=discord.ButtonStyle.danger, custom_id="civ_leave_btn")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user.id in self.participants:
            del self.participants[user.id]
            await self.update_embed(interaction=interaction)
            await interaction.followup.send("✅ 参加を辞退しました。", ephemeral=True)
        else:
            await interaction.response.send_message("まだ参加登録していません！", ephemeral=True)

# ==========================================
# 不在者削除用のセレクトUI (ホスト専用)
# ==========================================
class RemovePlayerSelect(discord.ui.Select):
    def __init__(self, public_view, original_message):
        options = [discord.SelectOption(label=p_name, value=str(p_id)) for p_id, p_name in public_view.participants.items()]
        if not options:
            options.append(discord.SelectOption(label="参加者がいません", value="none"))
        super().__init__(placeholder="辞退させるプレイヤーを選択", options=options, min_values=1, max_values=1)
        self.public_view = public_view
        self.original_message = original_message

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message("対象がいません。", ephemeral=True)
            
        p_id = int(self.values[0])
        if p_id in self.public_view.participants:
            removed_name = self.public_view.participants.pop(p_id)
            embed = self.original_message.embeds[0]
            member_list_str = "\n".join([f"・<@{i}>" for i in self.public_view.participants.keys()]) if self.public_view.participants else "現在参加者なし"
            embed.set_field_at(0, name=f"参加者一覧 ({len(self.public_view.participants)}名)", value=member_list_str, inline=False)
            await self.original_message.edit(embed=embed)
            await interaction.response.send_message(f"✅ {removed_name} を除外しました。", ephemeral=True)
        else:
            await interaction.response.send_message("既に除外されています。", ephemeral=True)

class RemovePlayerView(discord.ui.View):
    def __init__(self, public_view, original_message):
        super().__init__(timeout=120)
        self.add_item(RemovePlayerSelect(public_view, original_message))

# ==========================================
# 2. チーム分け後の公開用パネル (マップ投票ボタン表示)
# ==========================================
class TeamResultPublicView(discord.ui.View):
    def __init__(self, participants, host):
        super().__init__(timeout=None)
        self.participants = participants
        self.host = host
        self.map_votes_data = {}
        
        # 💡 BAN/PICKに引き継ぐためにチームメンバーのIDリストを保持できるように追加
        self.team_a_ids = []
        self.team_b_ids = []

    @discord.ui.button(label="🗺️ マップ投票", style=discord.ButtonStyle.success, custom_id="civ_vote_map_btn")
    async def vote_map_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.participants:
            return await interaction.response.send_message("⚠️ 対戦参加者のみ投票できます。", ephemeral=True)
            
        vote_view = MapVotingView(self, MAP_EMOJIS)
        await interaction.response.send_message(
            content="> 🗺️ プレイしたいマップをリストから選択してください...", 
            view=vote_view, 
            ephemeral=True
        )

# ==========================================
# 3. ホスト専用 操作パネル (募集フェーズ)
# ==========================================
class HostControlView(discord.ui.View):
    def __init__(self, public_message, public_view, host, sheet_manager):
        super().__init__(timeout=None)
        self.public_message = public_message
        self.public_view = public_view
        self.host = host
        self.sheet_manager = sheet_manager

    def is_authorized(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.host.id or interaction.user.guild_permissions.administrator

    @discord.ui.button(label="チーム分け実行", style=discord.ButtonStyle.primary, custom_id="civ_split_teams_btn", row=0)
    async def split_teams_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_authorized(interaction):
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        participants = self.public_view.participants
        if len(participants) < 2:
            return await interaction.response.send_message("チーム分けには最低2人必要です。", ephemeral=True)

        await interaction.response.defer()

        players_info = self.sheet_manager.get_player_scores(list(participants.keys()))
        for p_id, p_data in list(players_info.items()):
            if p_data is None:
                players_info[p_id] = {"name": f"未登録({str(p_id)[:5]})", "score": 3}

        team_a, team_b = balance_teams(players_info)
        
        score_a = sum(players_info[p_id]["score"] for p_id in team_a)
        score_b = sum(players_info[p_id]["score"] for p_id in team_b)
        
        team_a_str = "\n".join([f"・<@{p_id}> ({players_info[p_id]['score']})" for p_id in team_a]) if team_a else "なし"
        team_b_str = "\n".join([f"・<@{p_id}> ({players_info[p_id]['score']})" for p_id in team_b]) if team_b else "なし"

        result_public_view = TeamResultPublicView(participants, self.host)
        
        # 💡 ここでチームメンバー情報をTeamResultPublicViewに保存する
        result_public_view.team_a_ids = team_a
        result_public_view.team_b_ids = team_b

        embed = discord.Embed(title="チーム分け結果", color=discord.Color.gold())
        embed.add_field(name="【対戦設定】", value="🗺️ Map: **未定（現在メンバー投票中...）**", inline=False)
        embed.add_field(name=f"🔵 チームA (計: {score_a})", value=team_a_str, inline=True)
        embed.add_field(name=f"🔴 チームB (計: {score_b})", value=team_b_str, inline=True)

        try:
            await self.public_message.edit(embed=embed, view=result_public_view)
        except Exception as e:
            print(f"メッセージの編集に失敗: {e}")
            pass

        next_control_view = HostMapControlView(self.public_message, result_public_view, self.host, self.sheet_manager)
        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            content="✅ **チーム分けが完了しました！**\nメンバーのマップ投票を集計するため、タイミングを見て「マップ開票・決定」を押してください。",
            view=next_control_view
        )

    @discord.ui.button(label="不在者を外す", style=discord.ButtonStyle.secondary, custom_id="civ_remove_absent_btn", row=1)
    async def remove_absent_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_authorized(interaction):
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
        if not self.public_view.participants:
            return await interaction.response.send_message("参加者がいません。", ephemeral=True)
            
        remove_view = RemovePlayerView(public_view=self.public_view, original_message=self.public_message)
        await interaction.response.send_message("除外するプレイヤーを選択してください:", view=remove_view, ephemeral=True)

    @discord.ui.button(label="募集をキャンセル", style=discord.ButtonStyle.danger, custom_id="civ_cancel_btn", row=1)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_authorized(interaction):
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
        
        await self.public_message.delete()
        await interaction.response.edit_message(content="⚠️ 募集をキャンセルしました。", view=None)

# ==========================================
# 4. ホスト専用 操作パネル (マップ開票フェーズ)
# ==========================================
class HostMapControlView(discord.ui.View):
    def __init__(self, public_message, result_public_view, host, sheet_manager):
        super().__init__(timeout=None)
        self.public_message = public_message
        self.result_public_view = result_public_view
        self.host = host
        self.sheet_manager = sheet_manager

    def is_authorized(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.host.id or interaction.user.guild_permissions.administrator

    @discord.ui.button(label="🗺️ マップ開票・決定", style=discord.ButtonStyle.primary, custom_id="civ_decide_map_btn")
    async def decide_map_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_authorized(interaction):
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
        
        await interaction.response.defer()
        
        # 1. 投票の集計
        chosen_map, max_vote_val = calculate_map_votes(
            self.result_public_view.map_votes_data, 
            self.result_public_view.participants, 
            MAP_EMOJIS
        )
        
        map_result_str = f"🗺️ Map: **{chosen_map}** （{max_vote_val}票獲得）" if max_vote_val > 0 else f"🗺️ Map: **{chosen_map}**"
        
        # 2. 公開メッセージの更新 (マップ確定、投票ボタン消去)
        try:
            latest_msg = await interaction.channel.fetch_message(self.public_message.id)
            embed = latest_msg.embeds[0]
            embed.set_field_at(0, name="【対戦設定】", value=map_result_str, inline=False)
            await latest_msg.edit(embed=embed, view=None)
        except Exception:
            embed = self.public_message.embeds[0]
            if len(embed.fields) > 0:
                embed.set_field_at(0, name="【対戦設定】", value=map_result_str, inline=False)
            await self.public_message.edit(embed=embed, view=None)

        # 3. スプレッドシートへの対戦ログ記録
        map_votes_count = {name: 0 for name in MAP_EMOJIS.keys()}
        for p_id in self.result_public_view.participants.keys():
            if p_id in self.result_public_view.map_votes_data:
                voted = self.result_public_view.map_votes_data[p_id]
                if voted in map_votes_count:
                    map_votes_count[voted] += 1
                    
        # 💡 datetime.now() に JST を指定する
        match_data = {
            "match_id": f"MATCH-{datetime.datetime.now(JST).strftime('%Y%m%d-%H%M%S')}",
            "timestamp": datetime.datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S"),
            "host_id": str(self.host.id),
            "selected_map": chosen_map,
            "participant_count": len(self.result_public_view.participants),
            "total_votes": sum(map_votes_count.values()),
            "map_votes": map_votes_count
        }
        
        try:
            map_names = list(MAP_EMOJIS.keys())
            self.sheet_manager.record_match_log(match_data, map_names)
        except Exception as e:
            print(f"対戦ログの記録に失敗しました: {e}")

        # 4. 💡 全員へのマップ通知と、BAN/PICKへの移行ボタン送信
        participants_mention = " ".join([f"<@{p_id}>" for p_id in self.result_public_view.participants.keys()])
        
        bp_view = BanPickStartView(
            host=self.host,
            team_a=self.result_public_view.team_a_ids,
            team_b=self.result_public_view.team_b_ids,
            sheet_manager=self.sheet_manager,
            chosen_map=chosen_map,
            max_vote_val=max_vote_val
        )
        
        await interaction.channel.send(
            content=f"{participants_mention} \n🗺️ Map ： **【 {chosen_map} 】**に決定\n以下のボタンからBAN/PICKを開始してください。",
            view=bp_view
        )

        # 5. ホストの操作パネルを終了
        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            content="✅ マップ開票と集計が完了しました。", 
            view=None
        )