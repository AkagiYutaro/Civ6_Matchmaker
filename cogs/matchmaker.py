import os
import itertools
import discord
from discord import app_commands
from discord.ext import commands
from utils.sheet_manager import SheetManager

# ==========================================
# 1. 設定項目と定数
# ==========================================
SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY")
CREDS_FILE = os.getenv("CREDS_FILE", "credentials.json")

# マップ投票用のデフォルト絵文字設定
# （スプレッドシート等から動的取得できなかった場合の安全装置として残します）
DEFAULT_MAP_EMOJIS = {
     "七つの海": "7️⃣",
    "パンゲア": "🇵",
    "パンゲアウルティマ": "🇺",
    "湖": "🇱",
    "ハイランド": "🐴",
    "豊かな台地": "🌳",
    "群島": "🏝️",
    "地軸傾斜": "🏹",
    "シャッフル": "🎲"
}

# ==========================================
# 2. チーム均等化アルゴリズム
# ==========================================
def balance_teams(players_info: dict) -> tuple:
    """
    プレイヤーのスコア情報をもとに、戦力差が最も小さくなるように2チームに分割します。
    players_info: { discord_id: {"name": str, "score": int}, ... }
    戻り値: (team_a_ids, team_b_ids)
    """
    player_ids = list(players_info.keys())
    n = len(player_ids)
    
    if n < 2:
        return player_ids, []

    # 全体人数の半分（切り捨て）をチームAの定員とする
    team_a_size = n // 2
    best_diff = float('inf')
    best_team_a = []
    best_team_b = []
    
    # 全組み合わせ(全探索)の中から、スコア差が最小になる構成を見つける
    for team_a_tuple in itertools.combinations(player_ids, team_a_size):
        team_a_ids = list(team_a_tuple)
        team_b_ids = [pid for pid in player_ids if pid not in team_a_ids]
        
        score_a = sum(players_info[pid]["score"] for pid in team_a_ids)
        score_b = sum(players_info[pid]["score"] for pid in team_b_ids)
        
        diff = abs(score_a - score_b)
        
        if diff < best_diff:
            best_diff = diff
            best_team_a = team_a_ids
            best_team_b = team_b_ids
            
    return best_team_a, best_team_b

# ==========================================
# 3. Discord UIコンポーネント (募集パネル)
# ==========================================
class RemovePlayerSelect(discord.ui.Select):
    """ホストが不在者をリストから除外するためのドロップダウンメニュー"""
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
            # 親の募集パネル(Embed)を更新
            await self.parent_view.update_embed(original_message=self.original_message)
            await interaction.response.send_message(f"✅ {removed_name} を今回の参加者リストから除外しました。", ephemeral=True)
        else:
            await interaction.response.send_message("既に除外されています。", ephemeral=True)

class RemovePlayerView(discord.ui.View):
    def __init__(self, parent_view, original_message):
        super().__init__(timeout=120)
        self.add_item(RemovePlayerSelect(parent_view, original_message))


class MatchmakerView(discord.ui.View):
    """参加募集・チーム分けのメインパネル"""
    def __init__(self, host: discord.Member, sheet_manager: SheetManager):
        super().__init__(timeout=None) # 永続化
        self.host = host
        self.sheet_manager = sheet_manager
        # 初期状態では募集したホスト自身が参加状態になる
        self.participants = {host.id: host.display_name}

    async def update_embed(self, interaction: discord.Interaction = None, original_message: discord.Message = None):
        """現在の参加者リストを画面（Embed）に反映させる"""
        target_message = interaction.message if interaction else original_message
        if not target_message: return

        embed = target_message.embeds[0]
        member_list_str = "\n".join([f"・<@{p_id}>" for p_id in self.participants.keys()]) if self.participants else "現在参加者なし"
        embed.set_field_at(0, name=f"参加者一覧 ({len(self.participants)}名)", value=member_list_str, inline=False)
        
        if interaction:
            await interaction.response.edit_message(embed=embed, view=self)
        elif original_message:
            await original_message.edit(embed=embed, view=self)

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.success, custom_id="civ_join_btn", row=0)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        
        # 参加ボタンを押した際、スプレッドシートに登録があるかチェックする
        await interaction.response.defer(ephemeral=True)
        try:
            players_info = self.sheet_manager.get_player_scores([user.id])
            if players_info.get(user.id) is None:
                await interaction.followup.send(
                    "⚠️ **戦力バランスを計算するため、事前にスキル登録が必要です。**\n"
                    "管理者が設置した登録パネルからアンケートに答えてから、再度参加ボタンを押してください！",
                    ephemeral=True
                )
                return

            if user.id not in self.participants:
                self.participants[user.id] = user.display_name
                # パネルを更新（deferしているのでオリジナルメッセージを編集）
                await self.update_embed(original_message=interaction.message)
                await interaction.followup.send("✅ 参加登録しました！", ephemeral=True)
            else:
                await interaction.followup.send("既に登録されています！", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ データベースの確認中にエラーが発生しました: {e}", ephemeral=True)

    @discord.ui.button(label="辞退する", style=discord.ButtonStyle.danger, custom_id="civ_leave_btn", row=0)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user.id in self.participants:
            del self.participants[user.id]
            await self.update_embed(interaction=interaction)
        else:
            await interaction.response.send_message("まだ参加していません！", ephemeral=True)

    @discord.ui.button(label="不在者を外す", style=discord.ButtonStyle.secondary, custom_id="civ_remove_absent_btn", row=1)
    async def remove_absent_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("このボタンは募集ホストのみ押すことができます。", ephemeral=True)
            return
            
        if not self.participants:
            await interaction.response.send_message("参加者が誰もいません。", ephemeral=True)
            return

        remove_view = RemovePlayerView(parent_view=self, original_message=interaction.message)
        await interaction.response.send_message("リストから除外するプレイヤーを選択してください:", view=remove_view, ephemeral=True)

    @discord.ui.button(label="集計＆チーム分け（ホスト専用）", style=discord.ButtonStyle.primary, custom_id="civ_calc_btn", row=2)
    async def calc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("このボタンは募集ホストのみ押すことができます。", ephemeral=True)
            return
            
        if len(self.participants) < 2:
            await interaction.response.send_message("チーム分けには最低2人以上の参加者が必要です。", ephemeral=True)
            return

        await interaction.response.defer()
        
        try:
            # 最新の実力スコアをスプレッドシートから取得
            player_ids = list(self.participants.keys())
            players_info = self.sheet_manager.get_player_scores(player_ids)
            
            # チーム分けの実行
            team_a_ids, team_b_ids = balance_teams(players_info)
            
            # 結果のEmbed作成
            team_a_names = "\n".join([f"・<@{pid}> (Score: {players_info[pid]['score']})" for pid in team_a_ids]) or "なし"
            team_b_names = "\n".join([f"・<@{pid}> (Score: {players_info[pid]['score']})" for pid in team_b_ids]) or "なし"
            
            score_a = sum(players_info[pid]["score"] for pid in team_a_ids)
            score_b = sum(players_info[pid]["score"] for pid in team_b_ids)

            result_embed = discord.Embed(
                title="⚖️ チーム分け結果発表！",
                description="戦力が均等になるようにチームを割り当てました。",
                color=discord.Color.green()
            )
            result_embed.add_field(name=f"🔵 チームA (総合力: {score_a})", value=team_a_names, inline=False)
            result_embed.add_field(name=f"🔴 チームB (総合力: {score_b})", value=team_b_names, inline=False)
            result_embed.set_footer(text="GLHF! 良い試合を！")
            
            # パネルを無効化
            for child in self.children:
                child.disabled = True
            await interaction.followup.edit_message(message_id=interaction.message.id, view=self)
            
            # 結果送信
            await interaction.followup.send(content=f"ホスト <@{self.host.id}> がチームを確定しました！", embed=result_embed)
        except Exception as e:
            await interaction.followup.send(f"❌ チーム分け処理中にエラーが発生しました: {e}")

    @discord.ui.button(label="募集をキャンセル", style=discord.ButtonStyle.danger, custom_id="civ_cancel_btn", row=2)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("このボタンは募集ホストのみ押すことができます。", ephemeral=True)
            return
            
        await interaction.response.send_message(f"⚠️ ホスト <@{self.host.id}> が今回のCiv6マルチプレイ募集をキャンセル（解散）しました。")
        await interaction.message.delete()

# ==========================================
# 4. Cogクラス定義 (MatchmakerCog)
# ==========================================
class MatchmakerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # SheetManager の初期化と保持 (BOT全体で使い回せるようにする)
        try:
            if not SPREADSHEET_KEY:
                raise ValueError("環境変数 SPREADSHEET_KEY が設定されていません。")
            self.sheet_manager = SheetManager(SPREADSHEET_KEY, CREDS_FILE)
            self.bot.sheet_manager = self.sheet_manager
        except Exception as e:
            print(f"[CRITICAL ERROR] SheetManagerの初期化に失敗しました。BOTの一部機能が制限されます。\n -> {e}")
            self.sheet_manager = None

    @app_commands.command(name="civ_match", description="Civ6マルチプレイの参加登録とマップ投票、チーム分けを開始します。")
    async def civ_match(self, interaction: discord.Interaction):
        if not self.sheet_manager:
            await interaction.response.send_message("⚠️ データベースへの接続エラーが発生しているため、現在募集を開始できません。", ephemeral=True)
            return

        host = interaction.user
        
        # メンション用（適宜ROLE_IDを変更してください）
        ROLE_ID = os.getenv("MENTION_ROLE_ID", "123456789012345678")
        mention_str = f"<@&{ROLE_ID}>" if str(ROLE_ID).isdigit() else "@everyone"
        
        # ==========================================
        # ★ マップリストの動的取得処理 ★
        # スプレッドシートから取得を試み、失敗したらデフォルト値を使用する
        # ==========================================
        try:
            if hasattr(self.sheet_manager, "get_map_emojis"):
                map_emojis = self.sheet_manager.get_map_emojis()
                if not map_emojis: # リストが空の場合はフォールバック
                    map_emojis = DEFAULT_MAP_EMOJIS
            else:
                map_emojis = DEFAULT_MAP_EMOJIS
        except Exception as e:
            print(f"[WARNING] マップリストの取得に失敗したため、デフォルトを使用します: {e}")
            map_emojis = DEFAULT_MAP_EMOJIS

        embed = discord.Embed(
            title="⚔️ Civ6 マルチプレイ対戦募集！ ⚔️",
            description=f"{mention_str}\n\nホスト <@{host.id}> が募集を開始しました！\n"
                        "以下のボタンから「参加」または「辞退」を表明してください。\n"
                        "また、お好きなマップスタンプ（リアクション）に投票をお願いします。",
            color=discord.Color.blue()
        )
        embed.add_field(name="参加者一覧 (1名)", value=f"・<@{host.id}>", inline=False)
        
        view = MatchmakerView(host=host, sheet_manager=self.sheet_manager)
        
        # パネルの送信
        await interaction.response.send_message(content=mention_str, embed=embed, view=view)
        
        # リアクション(動的マップ投票)の追加
        try:
            sent_msg = await interaction.original_response()
            for emoji in map_emojis.values():
                await sent_msg.add_reaction(emoji)
        except Exception as e:
            print(f"[WARNING] リアクションの追加に失敗しました: {e}")

# ==========================================
# 5. Cogのセットアップ関数
# ==========================================
async def setup(bot: commands.Bot):
    # Cog を BOT に登録
    await bot.add_cog(MatchmakerCog(bot))