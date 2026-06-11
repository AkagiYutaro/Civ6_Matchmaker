import gspread
from google.oauth2.service_account import Credentials

class SheetManager:
    """Googleスプレッドシートとの通信とデータ処理を専門に行うクラス"""
    
    def __init__(self, spreadsheet_key: str, creds_file: str):
        self.scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        self.creds = Credentials.from_service_account_file(creds_file, scopes=self.scope)
        self.client = gspread.authorize(self.creds)
        self.sheet = self.client.open_by_key(spreadsheet_key)

    def get_map_emojis(self) -> dict:
        """「MAP」シートからマップ名と絵文字の定義を取得する"""
        try:
            ws = self.sheet.worksheet("MAP")
            records = ws.get_all_records()
            map_data = {}
            for row in records:
                map_name = str(row.get("マップ名", "")).strip()
                emoji = str(row.get("絵文字", "")).strip()
                if map_name and emoji:
                    map_data[map_name] = emoji
            return map_data
        except Exception as e:
            print(f"[ERROR] MAPシートの取得に失敗しました: {e}")
            return {}

    def get_master_flgs(self) -> list:
        """マスタ設定シートからアンケート(スキル)用のFLG名と配点を取得する"""
        try:
            config_ws = self.sheet.worksheet("マスタ設定")
            configs = config_ws.get_all_records()
            # FLG名が存在し、カテゴリが「スキル」のもののみ抽出
            return [{
                "flg_name": str(row.get("FLG名", "")),
                "score": int(row.get("現在の配点", 0)),
                "description": str(row.get("備考", "説明なし"))
            } for row in configs if row.get("FLG名") and str(row.get("カテゴリ", "")) == "スキル"]
        except Exception as e:
            print(f"[ERROR] マスター設定の取得失敗: {e}")
            return []

    def get_player_scores(self, discord_ids: list) -> dict:
        """
        指定されたDiscord IDリストのプレイヤーの総合スコアを取得する。
        戻り値: { 123456: {"name": "PlayerA", "score": 8}, 789012: None } 
        ※未登録の人は None が入る
        """
        try:
            players_ws = self.sheet.worksheet("プレイヤーデータ")
            all_players = players_ws.get_all_records()
            
            # 配点を取得して計算用に辞書化 {"FLG_内政": 3, "FLG_軍事": 2}
            flgs = self.get_master_flgs()
            weight_map = {item["flg_name"]: item["score"] for item in flgs}
            
            player_scores = {}
            for p_id in discord_ids:
                str_id = str(p_id)
                # 該当プレイヤーの行を探す
                player_row = next((p for p in all_players if str(p.get("Discord_ID")) == str_id), None)
                
                if player_row:
                    score = 0
                    # プレイヤーが持っている「1」のフラグと配点を掛け合わせて合算
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
                    # スプレッドシートに存在しない（未登録）
                    player_scores[p_id] = None
                    
            return player_scores
        except Exception as e:
            print(f"[ERROR] プレイヤースコアの読み込み失敗: {e}")
            raise e

    def register_or_update_player(self, discord_id: int, player_name: str, active_flgs: list) -> bool:
        """
        プレイヤーデータをスプレッドシートに新規登録、または既存のアンケート回答を上書き更新する。
        active_flgs: プレイヤーが選択したFLG名のリスト (例: ["FLG_内政", "FLG_戦争"])
        """
        try:
            players_ws = self.sheet.worksheet("プレイヤーデータ")
            headers = players_ws.row_values(1)
            
            if "Discord_ID" not in headers or "プレイヤー名" not in headers:
                print("[ERROR] プレイヤーデータシートの1行目に 'Discord_ID' または 'プレイヤー名' が見つかりません。")
                return False

            all_players = players_ws.get_all_records()
            str_id = str(discord_id)
            
            # CivNo（連番）の決定と既存行の特定
            row_idx = None
            existing_civ_no = 0
            max_civ_no = 0
            
            for idx, p in enumerate(all_players, start=2):
                val = p.get("CivNO", p.get("CivNo", 0))
                c_no = int(val) if str(val).isdigit() else 0
                if c_no > max_civ_no:
                    max_civ_no = c_no
                    
                if str(p.get("Discord_ID")) == str_id:
                    row_idx = idx
                    existing_civ_no = c_no

            target_civ_no = existing_civ_no if row_idx else max_civ_no + 1

            # ヘッダーの並びに合わせて書き込むデータ行(リスト)を作成
            row_data = []
            for h in headers:
                if h in ["CivNO", "CivNo"]:
                    row_data.append(target_civ_no)
                elif h == "Discord_ID":
                    row_data.append(str_id)
                elif h == "プレイヤー名":
                    row_data.append(player_name)
                elif h in ["WIN", "LOSE", "WinRate", "総プレイ数"]:
                    # 既存行があればそのままの数値を引き継ぎ、新規なら0にする
                    if row_idx:
                        row_data.append(all_players[row_idx - 2].get(h, 0))
                    else:
                        row_data.append(0)
                elif h in active_flgs:
                    row_data.append(1)  # 今回選択されたスキルは 1
                else:
                    row_data.append(0)  # 選択されなかったスキル、その他不明な列は 0

            # スプレッドシートへ書き込み
            if row_idx:
                end_col = gspread.utils.rowcol_to_a1(row_idx, len(row_data))
                players_ws.update(f"A{row_idx}:{end_col}", [row_data])
                print(f"[SUCCESS] プレイヤーデータを更新しました: {player_name}")
            else:
                players_ws.append_row(row_data)
                print(f"[SUCCESS] プレイヤーデータを新規登録しました: {player_name}")
                
            return True
        except Exception as e:
            print(f"[ERROR] スプレッドシートへの登録に失敗しました: {e}")
            return False
