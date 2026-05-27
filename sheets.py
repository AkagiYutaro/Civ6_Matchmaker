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