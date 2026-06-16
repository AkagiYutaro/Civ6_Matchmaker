import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# スプレッドシート管理クラス
# ==========================================
class SheetManager:
    def __init__(self, spreadsheet_key, creds_file):
        self.scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        self.creds = Credentials.from_service_account_file(creds_file, scopes=self.scope)
        self.client = gspread.authorize(self.creds)
        self.sheet = self.client.open_by_key(spreadsheet_key)

    def get_master_config(self):
        try:
            ws = self.sheet.worksheet("マスタ設定")
            return ws.get_all_records()
        except:
            return []

    def _ensure_player_sheet(self):
        try:
            ws = self.sheet.worksheet("プレイヤーデータ")
        except:
            ws = self.sheet.add_worksheet(title="プレイヤーデータ", rows="100", cols="20")
        
        master = self.get_master_config()
        # 固定統計列 + マスタから取得したスキルFLG
        skills = [m["FLG名"] for m in master if m.get("カテゴリ") == "スキル"]
        headers = ["CivNO", "Discord_ID", "プレイヤー名", "WIN", "LOSE", "WinRate", "総プレイ数"] + skills
        
        if ws.row_values(1) != headers:
            ws.update("A1", [headers])
        return ws

    def register_player(self, discord_id, name, skill_flgs):
        ws = self._ensure_player_sheet()
        all_data = ws.get_all_records()
        master = self.get_master_config()
        
        # 既存プレイヤー確認
        existing = next((r for r in all_data if str(r.get("Discord_ID")) == str(discord_id)), None)
        
        # 既存があればそのCivNOを再利用、なければ最大値+1
        if existing:
            civ_no = existing["CivNO"]
            row_idx = all_data.index(existing) + 2
        else:
            civ_no = max([int(r.get("CivNO", 0)) for r in all_data], default=0) + 1
            row_idx = len(all_data) + 2

        # スキルFLGと統計データの作成
        skills = [m["FLG名"] for m in master if m.get("カテゴリ") == "スキル"]
        row_data = [civ_no, str(discord_id), name, 0, 0, 0, 0] # 統計は初期0
        for s in skills:
            row_data.append(1 if s in skill_flgs else 0)
            
        ws.update(f"A{row_idx}", [row_data])
        return civ_no

    def get_player_scores(self, discord_ids):
        ws = self._ensure_player_sheet()
        master = self.get_master_config()
        weight_map = {m["FLG名"]: int(m["現在の配点"]) for m in master if m.get("カテゴリ") == "スキル"}
        all_data = ws.get_all_records()
        
        results = {}
        for p_id in discord_ids:
            row = next((r for r in all_data if str(r.get("Discord_ID")) == str(p_id)), None)
            if row:
                score = sum(int(row.get(f, 0)) * weight_map.get(f, 0) for f in weight_map if f in row)
                results[p_id] = {"name": row["プレイヤー名"], "score": score}
            else:
                results[p_id] = None
        return results

    # ==========================================
    # 📊 マップ統計機能 (新規追加)
    # ==========================================
    def _ensure_match_log_sheet(self, map_names: list) -> gspread.Worksheet:
        """対戦ログシートの存在確認と、動的なマップ列ヘッダーの自動拡張を行う"""
        try:
            ws = self.sheet.worksheet("対戦ログ")
        except gspread.exceptions.WorksheetNotFound:
            ws = self.sheet.add_worksheet(title="対戦ログ", rows="100", cols="20")
            
        base_headers = ["対戦ID", "実行日時", "募集ホストID", "採用マップ", "参加人数", "総投票数"]
        current_headers = ws.row_values(1)
        
        # 新規作成時などヘッダーが空の場合
        if not current_headers:
            headers = base_headers + map_names
            ws.update("A1", [headers])
            return ws

        # 既存ヘッダーに新しいマップ名がないか確認し、あれば右端に列を追加
        headers_updated = False
        headers = current_headers.copy()
        for m_name in map_names:
            if m_name not in headers:
                headers.append(m_name)
                headers_updated = True
                
        if headers_updated:
            ws.update("A1", [headers])
            
        return ws

    def record_match_log(self, match_data: dict, map_names: list) -> bool:
        """
        チーム分け確定時の対戦ログ（生データ）をスプレッドシートに追記する。
        各マップの得票数は、対応する列に自動的にマッピングされる。
        """
        try:
            ws = self._ensure_match_log_sheet(map_names)
            headers = ws.row_values(1)
            
            row_data = []
            for h in headers:
                if h == "対戦ID": 
                    row_data.append(match_data.get("match_id", ""))
                elif h == "実行日時": 
                    row_data.append(match_data.get("timestamp", ""))
                elif h == "募集ホストID": 
                    row_data.append(str(match_data.get("host_id", "")))
                elif h == "採用マップ": 
                    row_data.append(match_data.get("selected_map", ""))
                elif h == "参加人数": 
                    row_data.append(match_data.get("participant_count", 0))
                elif h == "総投票数": 
                    row_data.append(match_data.get("total_votes", 0))
                elif h in match_data.get("map_votes", {}):
                    # そのマップに入った票数を記録
                    row_data.append(match_data["map_votes"][h])
                else:
                    # その他のマップ（0票）、または関係ない列は 0 や空にする
                    if h in map_names:
                        row_data.append(0)
                    else:
                        row_data.append("")
                        
            ws.append_row(row_data)
            print(f"[SUCCESS] 対戦ログを記録しました: {match_data.get('match_id')}")
            return True
        except Exception as e:
            print(f"[ERROR] 対戦ログの記録に失敗しました: {e}")
            return False
