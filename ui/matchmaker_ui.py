import discord
from logic.matchmaker_logic import balance_teams, calculate_map_votes
import random

# 作成したマップ投票UIを読み込む
from ui.map_voting_ui import MapVotingView

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

class RemovePlayerSelect(discord.ui.Select):
    def __init__(self, parent_view, original_message):
        options = []
        for p_id, p_name in parent_view.participants.items():
            options.append(discord.SelectOption(label=p_name, value=str(p_id)))
        
        if not options:
            options.append(discord.SelectOption(label="参加者がいません", value="none"))

        super().__init__(placeholder="辞退させるプレイヤーを選択", options=options, min_values=1, max_values=1)
        self.parent_view = parent_view
        self.original_message = original_message

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("対象がいません。", ephemeral=True)
            return

        p_id = int(self.values[0])
        if p_id in self.parent_view.participants:
            removed_name = self.parent_view.participants.pop(p_id)
            await self.parent_view.update_embed(original_message=self.original_message)
            await interaction.response.send_message(f"✅ {removed_name} を今回の参加者リストから除外しました。", ephemeral=True)
        else:
            await interaction.response.send_message("既に除外されています。", ephemeral=True)

class RemovePlayerView(discord.ui.View):
    def __init__(self, parent_view, original_message):
        super().__init__(timeout=120)
        self.add_item(RemovePlayerSelect(parent_view, original_message))

class MatchmakerView(discord.ui.View):
    def __init__(self, host: discord.Member, sheet_manager):
        super().__init__(timeout=None)
        self.host = host
        self.sheet_manager = sheet_manager
        self.participants = {host.id: host.display_name}
        
        # 💡 追加: 投票データを保存する辞書 { user_id: "マップ名" }
        self.map_votes_data = {}

    async def update_embed(self, interaction: discord.Interaction = None, original_message: discord.Message = None):
        if interaction:
            embed = interaction.message.embeds[0]
        elif original_message:
            embed = original_message.embeds[0]
        else:
            return
            
        member_list_str = "\n".join([f"・<@{p_id}>" for p_id in self.participants.keys()]) if self.participants else "現在参加者なし"
        embed.set_field_at(0, name=f"参加者一覧 ({len(self.participants)}名)", value=member_list_str, inline=False)
        
        if interaction:
            await interaction.response.edit_message(embed=embed, view=self)
        elif original_message:
            try:
                await original_message.edit(embed=embed, view=self)
            except discord.errors.HTTPException:
                pass

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.success, custom_id="civ_join_btn", row=0)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        try:
            players_info = self.sheet_manager.get_player_scores([user.id])
        except Exception as e:
            await interaction.response.send_message(f"❌ **スプレッドシート接続エラー** ({e})", ephemeral=True)
            return

        if players_info[user.id] is None:
            await interaction.response.send_message("⚠️ **チーム分けのため事前にアンケートへの回答が必要です。**", ephemeral=True)
            return

        if user.id not in self.participants:
            self.participants[user.id] = user.display_name
            await self.update_embed(interaction=interaction)
        else:
            await interaction.response.send_message("既に登録されています！", ephemeral=True)

    @discord.ui.button(label="辞退する", style=discord.ButtonStyle.danger, custom_id="civ_leave_btn", row=0)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user.id in self.participants:
            del self.participants[user.id]
            
            # 💡 追加: 辞退した場合は投票データも消去する
            if user.id in self.map_votes_data:
                del self.map_votes_data[user.id]
                
            await self.update_embed(interaction=interaction)
        else:
            await interaction.response.send_message("まだ参加登録していません！", ephemeral=True)

    # 💡 追加: 🗺️ マップ投票ボタン
    @discord.ui.button(label="🗺️ マップに投票", style=discord.ButtonStyle.secondary, custom_id="civ_vote_map_btn", row=1)
    async def vote_map_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.participants:
            await interaction.response.send_message("⚠️ 先に「参加」ボタンを押してから投票してください。", ephemeral=True)
            return
            
        vote_view = MapVotingView(self, MAP_EMOJIS)
        await interaction.response.send_message(
            content="> 🗺️ プレイしたいマップをリストから選択してください...", 
            view=vote_view, 
            ephemeral=True
        )

    @discord.ui.button(label="不在者を外す", style=discord.ButtonStyle.secondary, custom_id="civ_remove_absent_btn", row=1)
    async def remove_absent_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("募集したホストのみ押すことができます。", ephemeral=True)
            return
            
        if len(self.participants) == 0:
            return

        remove_view = RemovePlayerView(parent_view=self, original_message=interaction.message)
        await interaction.response.send_message("除外するプレイヤーを選択してください:", view=remove_view, ephemeral=True)

    @discord.ui.button(label="チーム分け", style=discord.ButtonStyle.primary, custom_id="civ_calc_btn", row=2)
    async def calc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("募集したホストのみ押すことができます。", ephemeral=True)
            return

        if len(self.participants) < 2:
            await interaction.response.send_message("最低2人のプレイヤーが必要です！", ephemeral=True)
            return

        await interaction.response.defer()

        # ロジックモジュールを使用してマップ投票を集計
        chosen_map, max_vote_val = calculate_map_votes(self.map_votes_data, self.participants, MAP_EMOJIS)
        
        if max_vote_val > 0:
            map_result_str = f"🗺️ Map: **{chosen_map}** （{max_vote_val}票獲得）"
        else:
            map_result_str = f"🗺️ Map: **{chosen_map}**"

        players_info = self.sheet_manager.get_player_scores(list(self.participants.keys()))
        for p_id, p_data in list(players_info.items()):
            if p_data is None:
                players_info[p_id] = {"name": f"未登録({str(p_id)[:5]})", "score": 3}

        team_a, team_b = balance_teams(players_info)
        
        score_a = sum(players_info[p_id]["score"] for p_id in team_a)
        score_b = sum(players_info[p_id]["score"] for p_id in team_b)

        team_a_str = "\n".join([f"・<@{p_id}> ({players_info[p_id]['score']})" for p_id in team_a])
        team_b_str = "\n".join([f"・<@{p_id}> ({players_info[p_id]['score']})" for p_id in team_b])

        result_embed = discord.Embed(title="チーム分け結果", color=discord.Color.gold())
        result_embed.add_field(name="【対戦設定】", value=map_result_str, inline=False)
        result_embed.add_field(name=f"🔵 チームA (計: {score_a})", value=team_a_str, inline=True)
        result_embed.add_field(name=f"🔴 チームB (計: {score_b})", value=team_b_str, inline=True)

        for child in self.children:
            child.disabled = True
        
        original_msg = interaction.message
        await interaction.followup.edit_message(message_id=original_msg.id, view=self)
        await interaction.followup.send(embed=result_embed)

    @discord.ui.button(label="募集をキャンセル", style=discord.ButtonStyle.danger, custom_id="civ_cancel_btn", row=2)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("募集したホストのみ押すことができます。", ephemeral=True)
            return
            
        await interaction.response.send_message(f"⚠️ ホスト <@{self.host.id}> が今回の募集をキャンセルしました。")
        await interaction.message.delete()