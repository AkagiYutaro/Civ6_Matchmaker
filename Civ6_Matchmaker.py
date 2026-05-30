import os
import discord
from discord.ext import commands
from discord import app_commands
import gspread
from google.oauth2.service_account import Credentials
import itertools
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# .env ファイルから環境変数を読み込む
load_dotenv()

# ==========================================
# 1. 設定項目（環境に合わせて書き換えてください）
# ==========================================
# Google スプレッドシート設定（.envファイルから優先的に読み込みます）
SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY")
CREDENTIALS_FILE = os.getenv("CREDS_FILE", "credentials.json")  # 取得したGoogleサービスアカウントのJSONファイル名

# マップ投票用カスタム絵文字設定
# 書式: '表示名': '<:カスタム絵文字名:絵文字ID>' または '標準絵文字'
# ※カスタム絵文字IDの調べ方: Discordで「\:絵文字名:」と入力して送信すると取得できます。
MAP_EMOJIS = {
    "七つの海": "7️⃣",       # 例として標準の海の絵文字
    "パンゲア": "🇵",
    "パンゲアウルティマ": "🇺",
    "湖": "🇱",
    "豊かな台地": "🌳",
    "群島": "🏝️",          # 例として標準の島の絵文字
    "地軸傾斜": "🏹"
}

# ==========================================
# ダミーの Web サーバー (Render対応)
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

t = Thread(target=run)
t.start()

# ==========================================
# 2. スプレッドシート連携クラス
# ==========================================
class SheetManager:
    def __init__(self, spreadsheet_key, creds_file):
        self.scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        self.creds = Credentials.from_service_account_file(creds_file, scopes=self.scope)
        self.client = gspread.authorize(self.creds)
        self.sheet = self.client.open_by_key(spreadsheet_key)
        
    def get_player_scores(self, discord_ids):
        """指定されたDiscord IDリストのプレイヤーの総合スコアを取得する"""
        try:
            # 各シートを取得
            players_ws = self.sheet.worksheet("プレイヤーデータ")
            config_ws = self.sheet.worksheet("マスタ設定")
            
            # プレイヤーデータ全取得 (1行目はヘッダー)
            all_players = players_ws.get_all_records()
            # 設定データ（FLG名と配点）全取得
            configs = config_ws.get_all_records()
            
            # 配点を辞書化 {"FLG_内政": 3, "FLG_軍事": 2}
            weight_map = {row["FLG名"]: int(row["現在の配点"]) for row in configs if row.get("FLG名")}
            
            player_scores = {}
            
            for p_id in discord_ids:
                # 文字列型にして比較
                str_id = str(p_id)
                # スプレッドシートから該当ユーザーを検索
                player_row = next((p for p in all_players if str(p.get("Discord_ID")) == str_id), None)
                
                if player_row:
                    score = 0
                    # 各FLGの値(0 or 1)と、マスター設定の配点を掛け合わせて足す
                    for col_name, val in player_row.items():
                        if col_name in weight_map:
                            try:
                                score += int(val) * weight_map[col_name]
                            except ValueError:
                                pass
                    player_scores[p_id] = {
                        "name": player_row.get("プレイヤー名", f"ID: {str_id}"),
                        "score": score
                    }
                else:
                    # 登録がない新規プレイヤーは初期判定用に None を返して未登録を検出できるようにする
                    player_scores[p_id] = None
            return player_scores
        except Exception as e:
            print(f"[ERROR] スプレッドシート読み込み失敗: {e}")
            # エラー時はフォールバックせず、呼び出し元に例外を投げて原因を特定させる
            raise e

    def get_master_flgs(self):
        """マスター設定シートからFLG名と備考（説明）を取得する"""
        try:
            config_ws = self.sheet.worksheet("マスタ設定")
            configs = config_ws.get_all_records()
            # FLG名が存在するもののみ抽出
            return [{
                "flg_name": row["FLG名"],
                "score": int(row["現在の配点"]),
                "description": row.get("備考", "説明なし")
            } for row in configs if row.get("FLG名")]
        except Exception as e:
            print(f"[ERROR] マスター設定の取得失敗: {e}")
            return []

    def register_or_update_player(self, discord_id: int, player_name: str, active_flgs: list):
        """プレイヤーデータをスプレッドシートに登録、または既存データを上書き更新する"""
        try:
            players_ws = self.sheet.worksheet("プレイヤーデータ")
            
            # ヘッダー行を取得して列の配置を確定させる
            headers = players_ws.row_values(1)
            if "Discord_ID" not in headers or "プレイヤー名" not in headers:
                raise ValueError("プレイヤーデータシートのヘッダーに 'Discord_ID' または 'プレイヤー名' が存在しません。")

            all_players = players_ws.get_all_records()
            str_id = str(discord_id)
            
            # 書き込むレコードの構成
            row_data = []
            for h in headers:
                if h == "Discord_ID":
                    row_data.append(str_id)
                elif h == "プレイヤー名":
                    row_data.append(player_name)
                elif h in active_flgs:
                    row_data.append(1)  # 該当FLGを有効化
                else:
                    # プレイヤーデータにあるが、今回選択されなかったFLG、または未定義列は0にする
                    row_data.append(0)

            # 既存プレイヤーの検索 (スプレッドシートは2行目からデータ開始)
            row_idx = None
            for idx, p in enumerate(all_players, start=2):
                if str(p.get("Discord_ID")) == str_id:
                    row_idx = idx
                    break

            if row_idx:
                # 既存データの上書き (A列からヘッダーの長さ分の列を更新)
                end_col = gspread.utils.rowcol_to_a1(row_idx, len(row_data))
                players_ws.update(f"A{row_idx}:{end_col}", [row_data])
                print(f"[SUCCESS] プレイヤーデータを更新しました: {player_name}")
            else:
                # 新規登録
                players_ws.append_row(row_data)
                print(f"[SUCCESS] プレイヤーデータを新規登録しました: {player_name}")
            return True
        except Exception as e:
            print(f"[ERROR] スプレッドシートへの登録に失敗しました: {e}")
            return False

# ==========================================
# 3. チーム均等化アルゴリズム
# ==========================================
def balance_teams(players_info):
    """
    参加プレイヤーを2チームに分け、チームの合計スコア差が最小になる組み合わせ（全探索）を返す。
    """
    p_ids = list(players_info.keys())
    n = len(p_ids)
    half = n // 2
    
    best_diff = float("inf")
    best_team_a = []
    best_team_b = []
    
    # 全組み合わせの列挙 (N/2 人を選ぶ)
    for team_a_ids in itertools.combinations(p_ids, half):
        team_a_ids = list(team_a_ids)
        team_b_ids = [p for p in p_ids if p not in team_a_ids]
        
        score_a = sum(players_info[p_id]["score"] for p_id in team_a_ids)
        score_b = sum(players_info[p_id]["score"] for p_id in team_b_ids)
        
        diff = abs(score_a - score_b)
        
        if diff < best_diff:
            best_diff = diff
            best_team_a = team_a_ids
            best_team_b = team_b_ids
            
    return best_team_a, best_team_b

# ==========================================
# 4. Discord UIコンポーネント (募集ボタンとビュー)
# ==========================================
class MatchmakerView(discord.ui.View):
    def __init__(self, host: discord.Member, sheet_manager: SheetManager):
        super().__init__(timeout=None) # 永続化するためにタイムアウトなし
        self.host = host
        self.sheet_manager = sheet_manager
        self.participants = {host.id: host.display_name}  # 初期状態ではホストが参加

    async def update_embed(self, interaction: discord.Interaction):
        """参加者リストの表示を更新する"""
        embed = interaction.message.embeds[0]
        # フィールドの上書き
        member_list_str = "\n".join([f"・<@{p_id}>" for p_id in self.participants.keys()]) if self.participants else "現在参加者なし"
        embed.set_field_at(0, name=f"参加者一覧 ({len(self.participants)}名)", value=member_list_str, inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.success, custom_id="civ_join_btn")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        
        try:
            # スプレッドシートに登録があるかリアルタイム検証
            players_info = self.sheet_manager.get_player_scores([user.id])
        except Exception as e:
            await interaction.response.send_message(
                f"❌ **スプレッドシートの接続エラーが発生しました。**\n"
                f"シート名（「プレイヤーデータ」「マスタ設定」）が正しいか、"
                f"またAPI共有が完了しているか管理者に確認してください。\n"
                f"*(エラー詳細: {e})*",
                ephemeral=True
            )
            return

        if players_info[user.id] is None:
            # 未登録ユーザーは弾き、アンケート回答を促す
            await interaction.response.send_message(
                "⚠️ **チームの戦力バランスを計算するため、事前に自己申告アンケートへの回答が必要です。**\n"
                "サーバー内のスキル登録チャンネル（管理者が `/civ_setup_register` で設置した場所）にてアンケートに答えてから、再度参加ボタンを押してください！",
                ephemeral=True
            )
            return

        if user.id not in self.participants:
            self.participants[user.id] = user.display_name
            await self.update_embed(interaction)
        else:
            await interaction.response.send_message("既に登録されています！", ephemeral=True)

    @discord.ui.button(label="辞退する", style=discord.ButtonStyle.danger, custom_id="civ_leave_btn")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user.id in self.participants:
            del self.participants[user.id]
            await self.update_embed(interaction)
        else:
            await interaction.response.send_message("まだ参加登録していません！", ephemeral=True)

    @discord.ui.button(label="集計＆チーム分け（募集者のみ）", style=discord.ButtonStyle.primary, custom_id="civ_calc_btn")
    async def calc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 募集したホストのみ実行可能
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("このボタンは募集したホストのみ押すことができます。", ephemeral=True)
            return

        if len(self.participants) < 2:
            await interaction.response.send_message("チームを分けるには最低2人のプレイヤーが必要です！", ephemeral=True)
            return

        # 遅延処理のアナウンス
        await interaction.response.defer()

        # --------------------
        # 1. マップ投票リアクションの集計
        # --------------------
        original_msg = interaction.message
        # メッセージの最新情報をリアクション付きで取得
        channel = interaction.channel
        msg_with_reactions = await channel.fetch_message(original_msg.id)
        
        map_votes = {}
        # 設定された投票候補のスタンプのリアクション数をチェック
        for name, emoji in MAP_EMOJIS.items():
            reaction = discord.utils.get(msg_with_reactions.reactions, emoji=emoji)
            if reaction:
                # BOT自身のリアクション数(1)を差し引いてカウント
                map_votes[name] = reaction.count - 1
            else:
                map_votes[name] = 0

        # 最多票のマップを決定
        if map_votes and max(map_votes.values()) > 0:
            max_vote_val = max(map_votes.values())
            voted_maps = [k for k, v in map_votes.items() if v == max_vote_val]
            # 同率の場合は一番目の要素にする
            chosen_map = voted_maps[0]
            map_result_str = f"🗺️ 本日の戦場: **{chosen_map}** （{max_vote_val}票獲得）"
        else:
            chosen_map = "未投票（またはランダム）"
            map_result_str = f"🗺️ 本日の戦場: **{chosen_map}**"

        # --------------------
        # 2. スプレッドシートからスコアを取得しチーム分け
        # --------------------
        # スプレッドシートからデータ取得
        players_info = self.sheet_manager.get_player_scores(list(self.participants.keys()))
        
        # 万が一この時点で未登録者が入り込んでいた場合のエラーセーフ
        for p_id, p_data in list(players_info.items()):
            if p_data is None:
                players_info[p_id] = {"name": f"未登録({str(p_id)[:5]})", "score": 3}

        # チーム分け実行
        team_a, team_b = balance_teams(players_info)
        
        # チームスコア合計計算
        score_a = sum(players_info[p_id]["score"] for p_id in team_a)
        score_b = sum(players_info[p_id]["score"] for p_id in team_b)

        # --------------------
        # 3. 結果テキストの構築
        # --------------------
        team_a_str = "\n".join([f"・<@{p_id}> (スコア:{players_info[p_id]['score']})" for p_id in team_a])
        team_b_str = "\n".join([f"・<@{p_id}> (スコア:{players_info[p_id]['score']})" for p_id in team_b])

        result_embed = discord.Embed(
            title="🎮 Civ6 チーム分け結果発表！",
            color=discord.Color.gold()
        )
        result_embed.add_field(name="【対戦設定】", value=map_result_str, inline=False)
        result_embed.add_field(name=f"🔵 チームA (合計スコア: {score_a})", value=team_a_str, inline=True)
        result_embed.add_field(name=f"🔴 チームB (合計スコア: {score_b})", value=team_b_str, inline=True)
        result_embed.set_footer(text="楽しい対戦になりますように！GLHF!")

        # ボタンを無効化して結果を送信
        for child in self.children:
            child.disabled = True
        await interaction.followup.edit_message(message_id=original_msg.id, view=self)
        await interaction.followup.send(embed=result_embed)


# ==========================================
# 4.5. 自己申告アンケート用 UIコンポーネント
# ==========================================
class SkillDropdown(discord.ui.Select):
    def __init__(self, flg_list: list):
        # 複数選択を可能にするため、選択上限をFLGの数に、下限を0に設定
        max_vals = len(flg_list) if len(flg_list) > 0 else 1
        options = []
        for item in flg_list:
            # 備考（説明文）を短くカットしてラベルに収める
            short_desc = item["description"] if len(item["description"]) <= 50 else item["description"][:47] + "..."
            label_text = f"{item['flg_name'].replace('FLG_', '')}" # 見た目すっきり
            
            options.append(discord.SelectOption(
                label=label_text,
                value=item["flg_name"],
                description=f"配点: {item['score']}点 | {short_desc}"
            ))

        if not options:
            options.append(discord.SelectOption(label="設定されたFLGがありません", value="none"))

        super().__init__(
            placeholder="自分ができる能力にチェックを入れてください（複数選択可）",
            min_values=0,
            max_values=max_vals,
            options=options,
            custom_id="civ_skill_select"
        )

    async def callback(self, interaction: discord.Interaction):
        # 選択状態を確定させるため、一度送信ボタンを押すようにアナウンスする
        await interaction.response.defer(ephemeral=True)


class RegistrationFormView(discord.ui.View):
    def __init__(self, sheet_manager: SheetManager, flg_list: list):
        super().__init__(timeout=180) # 3分間操作がなければタイムアウト
        self.sheet_manager = sheet_manager
        self.flg_list = flg_list
        # ドロップダウンを追加
        self.dropdown = SkillDropdown(flg_list)
        self.add_item(self.dropdown)

    @discord.ui.button(label="この内容でスキルを登録する", style=discord.ButtonStyle.success, row=1)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 選択された値を取得
        selected_flgs = self.dropdown.values
        
        # 送信ボタンを一度無効にして処理中表示
        button.disabled = True
        await interaction.response.edit_message(view=self)
        
        # スプレッドシートにデータ書き込み (選択されたフラグを1に更新)
        player_name = interaction.user.display_name
        success = self.sheet_manager.register_or_update_player(
            discord_id=interaction.user.id,
            player_name=player_name,
            active_flgs=selected_flgs
        )

        if success:
            # 選択されたFLGの配点を合算して現在のレートスコアを算出
            total_score = sum(item["score"] for item in self.flg_list if item["flg_name"] in selected_flgs)
            
            selected_names = [f"・{f.replace('FLG_', '')}" for f in selected_flgs]
            selected_str = "\n".join(selected_names) if selected_names else "・なし（初期スコア）"

            embed = discord.Embed(
                title="✅ スキル登録が完了しました！",
                description=f"あなたのCiv6プレイヤー情報がスプレッドシートに連携されました。\n"
                            f"これでチーム分け（`/civ_match`）にいつでも参加できます！",
                color=discord.Color.green()
            )
            embed.add_field(name="登録プレイヤー名", value=player_name, inline=True)
            embed.add_field(name="算出された暫定スコア", value=f"**{total_score} 点**", inline=True)
            embed.add_field(name="申告した能力フラグ", value=selected_str, inline=False)
            embed.set_footer(text="※登録内容は再度「アンケートに回答する」ボタンから上書き更新が可能です。")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(
                "❌ データの保存中にエラーが発生しました。時間を置いてやり直すか、管理者に問い合わせてください。",
                ephemeral=True
            )


class RegisterChannelView(discord.ui.View):
    """登録チャンネルに常設しておくためのボタンビュー"""
    def __init__(self, sheet_manager: SheetManager):
        super().__init__(timeout=None) # 永続化
        self.sheet_manager = sheet_manager

    @discord.ui.button(label="アンケートに回答する", style=discord.ButtonStyle.primary, custom_id="civ_start_register_btn")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 処理が走るため先に待機
        await interaction.response.defer(ephemeral=True)
        
        try:
            # 既にスプレッドシートに登録があるかチェック
            players_info = self.sheet_manager.get_player_scores([interaction.user.id])
        except Exception as e:
            await interaction.followup.send(
                f"❌ **スプレッドシートの読み込みに失敗しました。**\n"
                f"スプレッドシートのID、シート名（「プレイヤーデータ」「マスタ設定」）が正しいか、"
                f"また認証用サービスアカウントへの「共有設定（編集者）」が完了しているか管理者に確認してください。\n"
                f"*(エラー詳細: {e})*",
                ephemeral=True
            )
            return

        # ==========================================
        # フロー分岐
        # ==========================================
        if players_info[interaction.user.id] is not None:
            # 【YES: すでに登録がある場合】
            await interaction.followup.send(
                "⚠️ **あなたはすでに登録されています。**\n"
                "追加回答や内容の上書き修正を行いたい場合は、管理者に直接お伝えください。",
                ephemeral=True
            )
            return
        
        # 【NO: 新規登録の場合】
        # 1. まずは初期値（全フラグを0）としてプレイヤーデータ行を作成
        player_name = interaction.user.display_name
        init_success = self.sheet_manager.register_or_update_player(
            discord_id=interaction.user.id,
            player_name=player_name,
            active_flgs=[] # 初期値はフラグチェックなし(すべて0)
        )

        if not init_success:
            await interaction.followup.send(
                "❌ プレイヤーの初期登録に失敗しました。管理者に確認してください。",
                ephemeral=True
            )
            return

        # 新規作成成功の通知
        await interaction.followup.send(
            f"🆕 **スプレッドシートに新規登録しました！** (プレイヤー名: {player_name})\n"
            f"続けて、自分の実力に合わせた能力アンケートに回答してください。",
            ephemeral=True
        )

        # 2. マスター設定からアンケート用FLG項目を読み込み
        flg_list = self.sheet_manager.get_master_flgs()
        
        if not flg_list:
            await interaction.followup.send(
                "⚠️ スプレッドシートの「マスタ設定」の取得に失敗したか、FLGが設定されていません。管理者に確認してください。",
                ephemeral=True
            )
            return

        # アンケート用のドロップダウンを「エフェメラル（本人限定）」で追加提示
        view = RegistrationFormView(self.sheet_manager, flg_list)
        await interaction.followup.send(
            "📋 **【Civ6 自己申告スキル登録】**\n"
            "あなたが実戦・マルチ等で「達成可能」「得意である」と自信を持って言える項目を、"
            "以下のメニューから**すべて**選択してください。\n"
            "選択し終えたら、下部にある「登録する」ボタンを押してください。",
            view=view,
            ephemeral=True
        )


# ==========================================
# 5. BOT基本クラスとイベントハンドラ
# ==========================================
class CivBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)
        self.sheet_manager = SheetManager(SPREADSHEET_KEY, CREDENTIALS_FILE)

    async def setup_hook(self):
        # スラッシュコマンドをDiscordに登録
        await self.tree.sync()
        print("[INFO] スラッシュコマンドが同期されました")
        
        # 永続Viewのリスナー登録（BOTが再起動してもアンケート常設ボタンを反応させるため）
        self.add_view(RegisterChannelView(self.sheet_manager))

bot = CivBot()

@bot.event
async def on_ready():
    print(f"[SUCCESS] ログインしました: {bot.user.name}")
    await bot.change_presence(activity=discord.Game(name="Civilization VI"))

# ==========================================
# 6. スラッシュコマンド (/civ_match)
# ==========================================
@bot.tree.command(name="civ_match", description="Civ6マルチプレイの参加登録とマップ投票、チーム分けを開始します。")
async def civ_match(interaction: discord.Interaction):
    host = interaction.user

    # メンションしたいロールIDをここに設定
    ROLE_ID = 1506354859790569504
    #1506555260204744714  # ここを自分のロールIDに書き換えてください
    mention_str = f"<@&{ROLE_ID}>"
    
    # 募集用メッセージの作成
    embed = discord.Embed(
        title="⚔️ Civ6 マルチプレイ対戦募集！ ⚔️",
        description=f"{mention_str}\n\nホスト <@{host.id}> が募集を開始しました！\n"
                    "以下のボタンから「参加」または「辞退」を表明してください。\n"
                    "また、お好きなマップスタンプ（リアクション）に投票をお願いします。",
        color=discord.Color.blue()
    )
    embed.add_field(name=f"参加者一覧", value=f"・<@{host.id}>", inline=False)
    
    # 投票可能なスタンプ一覧を説明に追加
    vote_guide = "\n".join([f"{emoji} : **{name}**" for name, emoji in MAP_EMOJIS.items()])
    embed.add_field(name="【マップ投票】", value=vote_guide, inline=False)
    
    # UIボタン付きViewを登録
    view = MatchmakerView(host=host, sheet_manager=bot.sheet_manager)
    
    # メッセージの送信
    await interaction.response.send_message(embed=embed, view=view)
    
    # 送信したメッセージオブジェクトを取得
    sent_msg = await interaction.original_response()
    
    # 投票用絵文字を自動リアクション追加
    for emoji in MAP_EMOJIS.values():
        try:
            await sent_msg.add_reaction(emoji)
        except Exception as e:
            print(f"[WARNING] リアクションの追加に失敗: {emoji} ({e})")


# ==========================================
# 6.5. 管理者用：スキルアンケート常設コマンド (/civ_setup_register)
# ==========================================
@bot.tree.command(name="civ_setup_register", description="【管理者専用】プレイヤー用の自己申告スキル登録パネルをこのチャンネルに設置します。")
@app_commands.default_permissions(administrator=True) # 管理者権限を持つメンバーのみ実行可能
async def civ_setup_register(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚔️ Civ6 マルチスキル自己申告アンケート ⚔️",
        description="Civ6マルチサーバーへようこそ！\n"
                    "対戦時の**チーム戦力を均等にして、全員が最高に面白い試合**を行えるようにするため、"
                    "プレイヤー全員にスキル登録をお願いしています。\n\n"
                    "初めて入室された方、まだ未登録の方、またはスキルレベルに変化があった方は、"
                    "以下のボタンからアンケートに回答して登録を済ませてください！\n\n"
                    "※登録を完了していないプレイヤーは、募集時の「参加ボタン」が押せなくなりますのでご注意ください。",
        color=discord.Color.dark_purple()
    )
    embed.add_field(
        name="📝 登録・更新方法",
        value="1. 下の「アンケートに回答する」ボタンを押す。\n"
              "2. 自分専用のドロップダウンが表示されるので、達成可能な能力項目を選択（複数可）。\n"
              "3. 送信ボタンを押して「登録完了」と表示されればOKです！",
        inline=False
    )
    embed.set_footer(text="マルチ環境の変化に合わせていつでも何度でも再登録可能です！")

    view = RegisterChannelView(bot.sheet_manager)
    await interaction.response.send_message(embed=embed, view=view)


# ==========================================
# 7. 起動処理
# ==========================================
if __name__ == "__main__":
    # 環境変数からトークンを読み込む
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        # ※直書きする場合はここにトークンを代入してください
        token = "あなたのDISCORD_BOT_TOKENをここに" 
        
    bot.run(token)
