import gspread
from google.oauth2.service_account import Credentials
import os

# ==========================================
# データベース管理者 (SheetManager)
# ==========================================
class SheetManager:
    """Google Sheets APIとの通信、プレイヤーデータの安全な読み書きを担当します。"""
    
    # プレイヤーデータシートの固定ヘッダー定義
    STATIC_HEADERS = ["CivNo", "Discord_ID", "プレイヤー名", "WIN", "LOSE", "WinRate", "総プレイ数"]

    def __init__(self, spreadsheet_key: str, creds_file: str):
        # Google APIのスコープ設定
        self.scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # 鍵ファイルの存在確認 (エラーの早期発見)
        if not os.path.exists(creds_file):
            raise FileNotFoundError(f"[ERROR] 認証ファイル '{creds_file}' が見つかりません。")
            
        try:
            self.creds = Credentials.from_service_account_file(creds_file, scopes=self.scope)
            self.client = gspread.authorize(self.creds)
            self.sheet = self.client.open_by_key(spreadsheet_key)
            print("[SUCCESS] スプレッドシートへの接続に成功しました。")
        except Exception as e:
            print(f"[CRITICAL ERROR] スプレッドシートの認証・接続に失敗: {e}")
            raise e

    def get_map_emojis(self) -> dict:
        """マスタ設定シートからマップ名と絵文字の定義を取得する"""
        try:
            ws = self.sheet.worksheet("マスタ設定")
            records = ws.get_all_records()
            map_data = {}
            for row in records:
                # 「カテゴリ」が「マップ」の行を抽出します
                if str(row.get("カテゴリ", "")).strip() == "マップ":
                    map_name = str(row.get("FLG名", "")).strip()
                    # 備考欄（または配点欄）に絵文字🌍を入れる想定です
                    emoji = str(row.get("備考", "")).strip()
                    if map_name and emoji:
                        map_data[map_name] = emoji
            return map_data
        except Exception as e:
            print(f"[ERROR] マップ設定の取得に失敗しました: {e}")
            return {}

    def get_master_config(self) -> list:
        """マスタ設定シートからスキル定義を取得する"""
        try:
            ws = self.sheet.worksheet("マスタ設定")
            records = ws.get_all_records()
            # 「カテゴリ」が「スキル」の行だけを抽出
            return [row for row in records if str(row.get("カテゴリ", "")).strip() == "スキル"]
        except Exception as e:
            print(f"[ERROR] マスタ設定の取得に失敗しました: {e}")
            return []

    def register_or_update_player(self, discord_id: int, player_name: str, skill_data: dict) -> bool:
        """
        プレイヤーの新規登録（オートインクリメント採番）、または既存データの更新を行う。
        API呼び出し回数を減らすため、行全体の一括更新(update)を使用するプロ仕様。
        """
        try:
            players_ws = self.sheet.worksheet("プレイヤーデータ")
            all_players = players_ws.get_all_records()
            str_id = str(discord_id)
            
            row_idx = None
            existing_civ_no = 0
            
            # 既存プレイヤーの検索
            for idx, p in enumerate(all_players, start=2):
                if str(p.get("Discord_ID")) == str_id:
                    row_idx = idx
                    val = p.get("CivNo", 0)
                    existing_civ_no = int(val) if str(val).isdigit() else 0
                    break
                    
            # CivNo 自動採番ロジック
            if row_idx:
                target_civ_no = existing_civ_no # 既存更新
            else:
                # 新規登録時は最大値を探して+1
                max_civ_no = max([int(p.get("CivNo", 0)) for p in all_players if str(p.get("CivNo", 0)).isdigit()], default=0)
                target_civ_no = max_civ_no + 1

            # マスタ設定の順序に合わせてフラグの配列を構築
            master_config = self.get_master_config()
            flags = [skill_data.get(m["FLG名"], 0) for m in master_config]

            # 書き込み用配列（固定ヘッダー分 + 変動フラグ分）
            row_data = [
                target_civ_no, 
                str_id, 
                player_name, 
                0, 0, 0, 0  # WIN, LOSE, WinRate, 総プレイ数の初期値
            ] + flags

            if row_idx:
                # 既存データの上書き (A列からデータの長さ分)
                end_col = gspread.utils.rowcol_to_a1(row_idx, len(row_data))
                players_ws.update(f"A{row_idx}:{end_col}", [row_data])
            else:
                # 新規追加
                players_ws.append_row(row_data)
                
            return True
        except Exception as e:
            print(f"[ERROR] プレイヤーデータの保存に失敗しました: {e}")
            return False

    def remove_player(self, discord_id: int) -> bool:
        """指定したDiscord IDのプレイヤーをスプレッドシートから物理削除する"""
        try:
            players_ws = self.sheet.worksheet("プレイヤーデータ")
            all_players = players_ws.get_all_records()
            str_id = str(discord_id)
            
            for idx, p in enumerate(all_players, start=2):
                if str(p.get("Discord_ID")) == str_id:
                    players_ws.delete_rows(idx)
                    return True
            return False
        except Exception as e:
            print(f"[ERROR] プレイヤーの削除に失敗しました: {e}")
            return False