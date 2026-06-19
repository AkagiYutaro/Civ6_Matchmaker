import gspread
from google.oauth2.service_account import Credentials
import os
import logging

# ==========================================
# ロガーの設定
# ==========================================
# main.py の設定を引き継いでフォーマットされたログを出力します
logger = logging.getLogger('discord.sheet_manager')

# ==========================================
# データベース管理者 (SheetManager)
# ==========================================
class SheetManager:
    """Google Sheets APIとの通信、プレイヤーデータの安全な読み書きを担当"""
    
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
            logger.info("[SUCCESS] スプレッドシートへの接続に成功しました。")
        except Exception as e:
            logger.error(f"[CRITICAL ERROR] スプレッドシートの認証・接続に失敗: {e}")
            raise e

    def get_map_emojis(self) -> dict:
        """「MAP」シートからマップ名と絵文字の定義を取得"""
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
            logger.error(f"[ERROR] MAPシートの取得に失敗しました: {e}")
            return {}

    def get_banpick_rules(self) -> list:
        """「BanPick」シートからルール名と絵文字、説明を取得"""
        try:
            ws = self.sheet.worksheet("BanPick")
            records = ws.get_all_records()
            rules = []
            for row in records:
                rule_name = str(row.get("ルール名", "")).strip()
                if rule_name:
                    rules.append({
                        "ルール名": rule_name,
                        "絵文字": str(row.get("絵文字", "")).strip(),
                        "説明（備考）": str(row.get("説明（備考）", "")).strip()
                    })
            return rules
        except Exception as e:
            logger.warning(f"[WARNING] BanPickシートが見つからないか取得に失敗しました: {e}")
            return []

    def get_master_config(self) -> list:
        """マスタ設定シートからスキル定義を取得する"""
        try:
            ws = self.sheet.worksheet("マスタ設定")
            records = ws.get_all_records()
            # 「カテゴリ」が「スキル」の行だけを抽出
            return [row for row in records if str(row.get("カテゴリ", "")).strip() == "スキル"]
        except Exception as e:
            logger.error(f"[ERROR] マスタ設定の取得に失敗しました: {e}")
            return []

    def get_player_scores(self, discord_ids: list) -> dict:
        """
        指定されたDiscord IDリストのプレイヤーの総合スコアを取得する
        ※チーム分けに必須のメソッド
        """
        try:
            players_ws = self.sheet.worksheet("プレイヤーデータ")
            all_players = players_ws.get_all_records()
            
            # マスタ設定から配点を取得して計算用に辞書化
            master_config = self.get_master_config()
            weight_map = {item.get("FLG名", ""): int(item.get("現在の配点", 0)) for item in master_config}
            
            player_scores = {}
            for p_id in discord_ids:
                str_id = str(p_id)
                player_row = next((p for p in all_players if str(p.get("Discord_ID")) == str_id), None)
                
                if player_row:
                    score = 0
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
                    player_scores[p_id] = None
                    
            return player_scores
        except Exception as e:
            logger.error(f"[ERROR] プレイヤースコアの読み込み失敗: {e}")
            raise e
        
    def register_or_update_player(self, discord_id: int, player_name: str, skill_data: dict) -> bool:
        """プレイヤーの新規登録（オートインクリメント採番）、または既存データの更新を行う。"""
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
                logger.info(f"[SUCCESS] プレイヤーデータを更新しました: {player_name}")
            else:
                # 新規追加
                players_ws.append_row(row_data)
                logger.info(f"[SUCCESS] プレイヤーデータを新規登録しました: {player_name}")
                
            return True
        except Exception as e:
            logger.error(f"[ERROR] プレイヤーデータの保存に失敗しました: {e}")
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
                    logger.info(f"[SUCCESS] プレイヤーを削除しました: ID {str_id}")
                    return True
            return False
        except Exception as e:
            logger.error(f"[ERROR] プレイヤーの削除に失敗しました: {e}")
            return False

    # ==========================================
    # 📈 対戦ログ記録機能 (Bプラン)
    # ==========================================
    def _ensure_match_log_sheet(self, map_names: list) -> gspread.Worksheet:
        """対戦ログシートの存在確認と、マップ列の自動拡張を行う"""
        try:
            ws = self.sheet.worksheet("対戦ログ")
        except gspread.exceptions.WorksheetNotFound:
            ws = self.sheet.add_worksheet(title="対戦ログ", rows="100", cols="20")
            logger.info("[INFO] '対戦ログ' ワークシートを自動新規作成しました。")
            
        base_headers = ["対戦ID", "実行日時", "募集ホストID", "採用マップ", "参加人数", "総投票数"]
        current_headers = ws.row_values(1)
        
        if not current_headers:
            ws.update("A1", [base_headers + map_names])
            return ws

        # 既存ヘッダーに新しいマップ名の列が足りなければ右端に追加
        headers = current_headers.copy()
        for m_name in map_names:
            if m_name not in headers:
                headers.append(m_name)
        
        if len(headers) > len(current_headers):
            ws.update("A1", [headers])
            logger.info("[INFO] 対戦ログのヘッダーを最新のマップ定義に同期しました。")
            
        return ws

    def record_match_log(self, match_data: dict, map_names: list) -> bool:
        """チーム分け確定時の対戦ログを記録し、MAPシートに統計を反映（カウント）する"""
        try:
            # --- 1. 対戦ログシートへの生データの追記 ---
            ws = self._ensure_match_log_sheet(map_names)
            headers = ws.row_values(1)
            row_data = []
            
            # 💡 バグ修正: match_dataのキーを正しく指定して値を取得するように変更
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
                elif h in map_names:
                    row_data.append(match_data.get("map_votes", {}).get(h, 0))
                else:
                    row_data.append("")
                        
            ws.append_row(row_data)
            logger.info(f"[SUCCESS] 対戦ログを記録しました: {match_data.get('match_id')}")

            # --- 2. MAPシートへの統計カウント更新 ---
            try:
                ws_map = self.sheet.worksheet("MAP")
                map_records = ws_map.get_all_records()
                map_headers = ws_map.row_values(1)
                
                # 💡 修正: MAPシートには純粋な「統計情報」のみを集計させるようにスリム化
                stat_headers = ["採用回数", "累計獲得票数", "累計参加人数"]
                headers_updated = False
                for h in stat_headers:
                    if h not in map_headers:
                        map_headers.append(h)
                        headers_updated = True
                
                if headers_updated:
                    ws_map.update("A1", [map_headers])
                    map_records = ws_map.get_all_records()
                
                selected_map = match_data.get("selected_map", "")
                updates = []
                
                for idx, row in enumerate(map_records, start=2): # 1行目はヘッダーのため2行目から
                    m_name = str(row.get("マップ名", "")).strip()
                    if not m_name:
                        continue
                        
                    play_count = int(row.get("採用回数", 0) or 0)
                    total_votes = int(row.get("累計獲得票数", 0) or 0)
                    total_participants = int(row.get("累計参加人数", 0) or 0)
                    
                    is_dirty = False
                    
                    # 獲得票数の加算
                    votes_for_this_map = match_data.get("map_votes", {}).get(m_name, 0)
                    if votes_for_this_map > 0:
                        total_votes += votes_for_this_map
                        is_dirty = True
                        
                    # 採用されたマップのカウントアップ
                    if m_name == selected_map:
                        play_count += 1
                        total_participants += match_data.get("participant_count", 0)
                        is_dirty = True
                        
                    if is_dirty:
                        new_row = []
                        for h in map_headers:
                            if h == "マップ名": new_row.append(row.get("マップ名", ""))
                            elif h == "絵文字": new_row.append(row.get("絵文字", ""))
                            elif h == "採用回数": new_row.append(play_count)
                            elif h == "累計獲得票数": new_row.append(total_votes)
                            elif h == "累計参加人数": new_row.append(total_participants)
                            else: new_row.append(row.get(h, ""))
                            
                        end_col = gspread.utils.rowcol_to_a1(idx, len(new_row))
                        updates.append({"range": f"A{idx}:{end_col}", "values": [new_row]})
                
                if updates:
                    ws_map.batch_update(updates)
                    logger.info("[SUCCESS] MAPシートの統計を更新しました。")
                    
            except Exception as e:
                logger.warning(f"[WARNING] MAPシートの統計更新に失敗しました: {e}")

            return True
        except Exception as e:
            logger.error(f"[ERROR] 対戦ログの記録失敗: {e}")
            return False