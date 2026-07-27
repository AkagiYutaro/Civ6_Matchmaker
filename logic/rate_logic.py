def calculate_new_rates(team_a_ids: list, team_b_ids: list, win_team: str, current_rates: dict) -> dict:
    """
    Eloレーティングシステムによるレート計算
    current_rates: { user_id: current_rate, ... }
    returns: { user_id: {"old": rate, "new": new_rate, "diff": diff}, ... }
    """
    # 各チームの平均レートを算出（初期値は1500とする）
    avg_a = sum(current_rates.get(uid, 1500) for uid in team_a_ids) / len(team_a_ids) if team_a_ids else 1500
    avg_b = sum(current_rates.get(uid, 1500) for uid in team_b_ids) / len(team_b_ids) if team_b_ids else 1500

    # 期待勝率の計算
    e_a = 1 / (1 + 10 ** ((avg_b - avg_a) / 400))
    e_b = 1 / (1 + 10 ** ((avg_a - avg_b) / 400))

    # 勝敗スコア (1: 勝利, 0: 敗北)
    score_a = 1 if win_team == "チームA" else 0
    score_b = 1 if win_team == "チームB" else 0

    # 変動定数 K
    K = 32
    diff_a = round(K * (score_a - e_a))
    diff_b = round(K * (score_b - e_b))

    results = {}
    for uid in team_a_ids:
        old_r = current_rates.get(uid, 1500)
        new_r = old_r + diff_a
        results[uid] = {"old": old_r, "new": new_r, "diff": diff_a}
        
    for uid in team_b_ids:
        old_r = current_rates.get(uid, 1500)
        new_r = old_r + diff_b
        results[uid] = {"old": old_r, "new": new_r, "diff": diff_b}

    return results