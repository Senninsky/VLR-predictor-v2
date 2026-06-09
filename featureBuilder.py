# Importations
from datetime import datetime
from itertools import combinations
import math
import statistics


# FeatureState
class FeatureState:
    def __init__(self):
        self.default_elo = 1500.0
        self.elo_k = 32.0
        self.player_histories = {}
        self.player_elos = {}
        self.player_last_lineups = {}
        self.pair_stats = {}
        self.lineup_stats = {}
        self.four_player_lineup_stats = {}
        self.global_stat_sums = {}
        self.global_stat_counts = {}
        self.stat_names = ["r", "acs", "kast", "adr", "hs", "fpm", "kd", "fkfd", "a"]
        self.model_stat_names = ["r", "acs", "kast", "adr", "hs", "fpm", "kd", "fkfd"]

    def build_team_features(self, player_ids, date_time):
        player_ids = self._clean_player_ids(player_ids)
        lineup_id = self._get_lineup_id(player_ids)
        histories = [self.player_histories.get(player_id, []) for player_id in player_ids]
        history_counts = [len(history) for history in histories]
        player_rows = self._get_player_feature_rows(player_ids, histories, date_time)

        features = {
            "player_amount": len(player_ids),
            "unique_player_amount": len(set(player_ids)),
            "mean_hist_n": self._mean(history_counts),
            "min_hist_n": min(history_counts) if history_counts else 0.0,
            "max_hist_n": max(history_counts) if history_counts else 0.0,
            "low_history_count": sum(1 for amount in history_counts if amount < 5),
            "zero_history_count": sum(1 for amount in history_counts if amount == 0),
            "player_history_counts": history_counts,
            "player_10_average_ratings": [row["average_r"] for row in player_rows],
            "10_average_ratings": self._mean([row["average_r"] for row in player_rows]),
        }

        self._add_player_slot_features(features, player_rows)
        self._add_stat_aggregate_features(features, player_rows)
        self._add_spread_features(features, player_rows)
        self._add_rest_load_features(features, histories, date_time)
        self._add_lineup_features(features, lineup_id)
        self._add_pair_features(features, player_ids)
        self._add_elo_features(features, player_ids, history_counts)
        self._add_opponent_adjusted_features(features, histories)
        self._add_role_balance_features(features, player_rows)

        return features

    def create_match_update(self, match, date_time):
        team_1_player_ids = self._get_match_player_ids(match.team_1.players)
        team_2_player_ids = self._get_match_player_ids(match.team_2.players)
        team_1_won = match.team_1.score > match.team_2.score
        team_2_won = match.team_2.score > match.team_1.score
        team_1_expected = self._get_expected_win_probability(team_1_player_ids, team_2_player_ids)
        team_2_expected = 1.0 - team_1_expected

        return {
            "date_time": date_time,
            "team_1": self._create_team_update(match.team_1.players, team_1_won, team_1_expected),
            "team_2": self._create_team_update(match.team_2.players, team_2_won, team_2_expected),
        }

    def apply_update(self, update):
        self._apply_team_update(update["team_1"], update["date_time"])
        self._apply_team_update(update["team_2"], update["date_time"])
        self._apply_elo_update(update["team_1"], update["team_2"])

    def _get_player_feature_rows(self, player_ids, histories, date_time):
        rows = []

        for player_id, history in zip(player_ids, histories):
            recent_history = history[-50:]
            row = {
                "player_id": player_id,
                "hist_n": len(history),
                "elo": self._get_player_elo(player_id),
            }

            for stat_name in self.stat_names:
                values = self._get_history_stat_values(history, stat_name)
                row["average_" + stat_name] = self._last_average(values, 10)
                row["ewm_short_" + stat_name] = self._get_ewm_stat(recent_history, stat_name, date_time, 14)
                row["ewm_long_" + stat_name] = self._get_ewm_stat(recent_history, stat_name, date_time, 60)
                row["trend_" + stat_name] = row["ewm_short_" + stat_name] - row["ewm_long_" + stat_name]
                row["shrunk_" + stat_name] = self._shrunk_mean(
                    row["ewm_long_" + stat_name],
                    len(values),
                    self._get_global_mean(stat_name),
                )

            row["entry_pressure"] = row["shrunk_fkfd"]
            row["support_index"] = row["shrunk_a"] + (row["shrunk_kast"] / 100)
            row["control_index"] = (row["shrunk_kast"] / 100) + (row["shrunk_adr"] / 100)
            rows.append(row)

        rows = sorted(rows, key=self._get_player_sort_key, reverse=True)

        return rows

    def _add_player_slot_features(self, features, player_rows):
        for index in range(5):
            row = self._get_player_row_or_empty(player_rows, index)
            slot = "player_" + str(index + 1) + "_"

            features[slot + "hist_n"] = row["hist_n"]
            features[slot + "elo"] = row["elo"]

            for stat_name in self.model_stat_names:
                features[slot + "shrunk_" + stat_name] = row["shrunk_" + stat_name]
                features[slot + "trend_" + stat_name] = row["trend_" + stat_name]

    def _add_stat_aggregate_features(self, features, player_rows):
        for stat_name in self.model_stat_names:
            values = [row["shrunk_" + stat_name] for row in player_rows]
            trend_values = [row["trend_" + stat_name] for row in player_rows]

            self._add_distribution_features(features, stat_name + "_shrunk", values)
            self._add_distribution_features(features, stat_name + "_trend", trend_values)

    def _add_spread_features(self, features, player_rows):
        rating_values = [row["shrunk_r"] for row in player_rows]
        acs_values = [row["shrunk_acs"] for row in player_rows]
        kast_values = [row["shrunk_kast"] for row in player_rows]
        fkfd_values = sorted([row["shrunk_fkfd"] for row in player_rows], reverse=True)

        features["floor_rating"] = self._bottom_average(rating_values, 2)
        features["floor_kast"] = min(kast_values) if kast_values else 0.0
        features["top1_share_acs"] = self._top_share(acs_values, 1)
        features["top2_share_rating"] = self._top_share(rating_values, 2)
        features["max_fkfd"] = fkfd_values[0] if fkfd_values else 0.0
        features["second_fkfd"] = fkfd_values[1] if len(fkfd_values) > 1 else 0.0
        features["top_minus_bottom_rating_gap"] = max(rating_values) - min(rating_values) if rating_values else 0.0

    def _add_rest_load_features(self, features, histories, date_time):
        days_since_last_match = []
        matches_last_7d = []
        matches_last_14d = []
        unknown_rest_count = 0

        for history in histories:
            history_dates = [entry["date_time"] for entry in history]

            if history_dates:
                last_date_time = max(history_dates)
                days_since = max((date_time - last_date_time).total_seconds() / 86400, 0.0)
            else:
                days_since = 30.0
                unknown_rest_count += 1

            days_since_last_match.append(days_since)
            matches_last_7d.append(self._count_recent_matches(history_dates, date_time, 7))
            matches_last_14d.append(self._count_recent_matches(history_dates, date_time, 14))

        features["days_since_last_match_mean"] = self._mean(days_since_last_match)
        features["days_since_last_match_min"] = min(days_since_last_match) if days_since_last_match else 30.0
        features["matches_last_7d_mean"] = self._mean(matches_last_7d)
        features["matches_last_14d_mean"] = self._mean(matches_last_14d)
        features["back_to_back_flag"] = float(any(days <= 1.5 for days in days_since_last_match))
        features["unknown_rest_count"] = unknown_rest_count

    def _add_lineup_features(self, features, lineup_id):
        lineup = self.lineup_stats.get(lineup_id, {"matches": 0.0, "wins": 0.0})
        same4plus_counts = [
            self.four_player_lineup_stats.get(four_player_lineup_id, {"matches": 0.0})["matches"]
            for four_player_lineup_id in combinations(lineup_id, 4)
        ]

        features["same5_prior_matches"] = lineup["matches"]
        features["same5_prior_winrate"] = self._safe_divide(lineup["wins"], lineup["matches"])
        features["same4plus_recent_count"] = max(same4plus_counts) if same4plus_counts else 0.0
        features["overlap_with_last_match"] = self._get_overlap_with_last_match(lineup_id)

    def _add_pair_features(self, features, player_ids):
        pair_matches = []
        pair_winrates = []

        for pair_id in self._get_pair_ids(player_ids):
            pair = self.pair_stats.get(pair_id, {"matches": 0.0, "wins": 0.0})
            pair_matches.append(pair["matches"])
            pair_winrates.append(self._safe_divide(pair["wins"], pair["matches"]))

        features["pair_matches_mean"] = self._mean(pair_matches)
        features["pair_matches_min"] = min(pair_matches) if pair_matches else 0.0
        features["pair_winrate_mean"] = self._mean(pair_winrates)
        features["pair_winrate_std"] = self._std(pair_winrates)

    def _add_elo_features(self, features, player_ids, history_counts):
        elos = [self._get_player_elo(player_id) for player_id in player_ids]
        conservative_elos = []

        for elo, history_count in zip(elos, history_counts):
            uncertainty = 350 / math.sqrt(history_count + 1)
            conservative_elos.append(elo - (3 * uncertainty))

        features["elo_sum"] = sum(elos)
        features["elo_mean"] = self._mean(elos)
        features["elo_min"] = min(elos) if elos else self.default_elo
        features["elo_max"] = max(elos) if elos else self.default_elo
        features["elo_std"] = self._std(elos)
        features["elo_conservative_sum"] = sum(conservative_elos)

    def _add_opponent_adjusted_features(self, features, histories):
        residuals = []

        for history in histories:
            player_residuals = [entry["win_residual"] for entry in history[-10:]]
            residuals.append(self._mean(player_residuals))

        features["opponent_adjusted_win_residual_mean"] = self._mean(residuals)
        features["opponent_adjusted_win_residual_min"] = min(residuals) if residuals else 0.0

    def _add_role_balance_features(self, features, player_rows):
        entry_values = [row["entry_pressure"] for row in player_rows]
        support_values = [row["support_index"] for row in player_rows]
        control_values = [row["control_index"] for row in player_rows]
        sorted_entry_values = sorted(entry_values, reverse=True)

        features["entry_pressure_mean"] = self._mean(entry_values)
        features["entry_imbalance"] = self._get_index_or_zero(sorted_entry_values, 0) - self._get_index_or_zero(sorted_entry_values, 1)
        features["support_index_mean"] = self._mean(support_values)
        features["support_index_std"] = self._std(support_values)
        features["control_index_mean"] = self._mean(control_values)
        features["control_index_std"] = self._std(control_values)

    def _create_team_update(self, team_players, won, expected_win_probability):
        player_ids = self._get_match_player_ids(team_players)
        player_updates = []

        for team_player in team_players:
            player_updates.append({
                "player_id": str(team_player.player.id),
                "stats": self._get_performance_stats(team_player.performance),
            })

        return {
            "player_ids": player_ids,
            "lineup_id": self._get_lineup_id(player_ids),
            "won": float(won),
            "expected_win_probability": expected_win_probability,
            "player_updates": player_updates,
        }

    def _apply_team_update(self, team_update, date_time):
        lineup_id = team_update["lineup_id"]
        lineup = self._get_counting_stat(self.lineup_stats, lineup_id)
        lineup["matches"] += 1
        lineup["wins"] += team_update["won"]

        for four_player_lineup_id in combinations(lineup_id, 4):
            four_player_lineup = self._get_counting_stat(self.four_player_lineup_stats, four_player_lineup_id)
            four_player_lineup["matches"] += 1
            four_player_lineup["wins"] += team_update["won"]

        for pair_id in self._get_pair_ids(team_update["player_ids"]):
            pair = self._get_counting_stat(self.pair_stats, pair_id)
            pair["matches"] += 1
            pair["wins"] += team_update["won"]

        for player_update in team_update["player_updates"]:
            self._add_player_history(player_update, team_update, date_time)
            self.player_last_lineups[player_update["player_id"]] = lineup_id

    def _apply_elo_update(self, team_1_update, team_2_update):
        if not team_1_update["player_ids"] or not team_2_update["player_ids"]:
            return

        team_1_delta = self.elo_k * (team_1_update["won"] - team_1_update["expected_win_probability"])
        team_2_delta = self.elo_k * (team_2_update["won"] - team_2_update["expected_win_probability"])

        self._apply_player_elo_delta(team_1_update["player_ids"], team_1_delta)
        self._apply_player_elo_delta(team_2_update["player_ids"], team_2_delta)

    def _add_player_history(self, player_update, team_update, date_time):
        player_id = player_update["player_id"]

        if player_id not in self.player_histories:
            self.player_histories[player_id] = []

        self.player_histories[player_id].append({
            "date_time": date_time,
            "stats": player_update["stats"],
            "won": team_update["won"],
            "expected_win_probability": team_update["expected_win_probability"],
            "win_residual": team_update["won"] - team_update["expected_win_probability"],
        })

        for stat_name, value in player_update["stats"].items():
            if value is None:
                continue

            self.global_stat_sums[stat_name] = self.global_stat_sums.get(stat_name, 0.0) + value
            self.global_stat_counts[stat_name] = self.global_stat_counts.get(stat_name, 0) + 1

    def _get_performance_stats(self, performance):
        stats = {
            "r": self._to_float_or_none(performance.r),
            "acs": self._to_float_or_none(performance.acs),
            "k": self._to_float_or_none(performance.k),
            "d": self._to_float_or_none(performance.d),
            "a": self._to_float_or_none(performance.a),
            "kast": self._to_float_or_none(performance.kast),
            "adr": self._to_float_or_none(performance.adr),
            "hs": self._to_float_or_none(performance.hs),
            "fk": self._to_float_or_none(performance.fk),
            "fd": self._to_float_or_none(performance.fd),
            "fpm": self._to_float_or_none(performance.fpm),
        }

        if stats["k"] is not None and stats["d"] is not None:
            stats["kd"] = (stats["k"] + 1.0) / (stats["d"] + 1.0)
        else:
            stats["kd"] = None

        if stats["fk"] is not None and stats["fd"] is not None:
            stats["fkfd"] = (stats["fk"] + 0.5) / (stats["fd"] + 0.5)
        else:
            stats["fkfd"] = None

        return stats

    def _get_ewm_stat(self, history, stat_name, date_time, half_life_days):
        values = []
        weights = []

        for entry in history:
            value = entry["stats"].get(stat_name)

            if value is None:
                continue

            age_days = max((date_time - entry["date_time"]).total_seconds() / 86400, 0.0)
            weight = math.exp(-math.log(2) * age_days / half_life_days)
            values.append(value)
            weights.append(weight)

        if not values or not weights or sum(weights) == 0:
            return 0.0

        return sum(value * weight for value, weight in zip(values, weights)) / sum(weights)

    def _get_expected_win_probability(self, team_1_player_ids, team_2_player_ids):
        team_1_elo = self._mean([self._get_player_elo(player_id) for player_id in team_1_player_ids])
        team_2_elo = self._mean([self._get_player_elo(player_id) for player_id in team_2_player_ids])
        return 1 / (1 + (10 ** ((team_2_elo - team_1_elo) / 400)))

    def _apply_player_elo_delta(self, player_ids, delta):
        if not player_ids:
            return

        player_delta = delta / len(player_ids)

        for player_id in player_ids:
            self.player_elos[player_id] = self._get_player_elo(player_id) + player_delta

    def _get_player_elo(self, player_id):
        return self.player_elos.get(str(player_id), self.default_elo)

    def _get_match_player_ids(self, team_players):
        return [str(team_player.player.id) for team_player in team_players]

    def _clean_player_ids(self, player_ids):
        cleaned_player_ids = []

        for player_id in player_ids:
            if player_id is None:
                continue

            player_id = str(player_id)

            if player_id in cleaned_player_ids:
                continue

            cleaned_player_ids.append(player_id)

        return cleaned_player_ids[:5]

    def _get_lineup_id(self, player_ids):
        return tuple(sorted(self._clean_player_ids(player_ids)))

    def _get_pair_ids(self, player_ids):
        return [tuple(sorted(pair)) for pair in combinations(self._clean_player_ids(player_ids), 2)]

    def _get_counting_stat(self, stats, stat_id):
        if stat_id not in stats:
            stats[stat_id] = {"matches": 0.0, "wins": 0.0}

        return stats[stat_id]

    def _get_overlap_with_last_match(self, lineup_id):
        overlaps = []
        lineup_players = set(lineup_id)

        for player_id in lineup_id:
            last_lineup_id = self.player_last_lineups.get(player_id)

            if not last_lineup_id:
                continue

            overlaps.append(len(lineup_players & set(last_lineup_id)) / 5)

        return self._mean(overlaps)

    def _get_player_sort_key(self, row):
        return row["shrunk_r"], row["elo"], row["hist_n"]

    def _get_player_row_or_empty(self, player_rows, index):
        if index < len(player_rows):
            return player_rows[index]

        row = {
            "hist_n": 0.0,
            "elo": self.default_elo,
        }

        for stat_name in self.stat_names:
            row["average_" + stat_name] = 0.0
            row["shrunk_" + stat_name] = self._get_global_mean(stat_name)
            row["trend_" + stat_name] = 0.0

        return row

    def _get_history_stat_values(self, history, stat_name):
        return [
            entry["stats"][stat_name]
            for entry in history
            if entry["stats"].get(stat_name) is not None
        ]

    def _last_average(self, values, amount):
        return self._mean(values[-amount:])

    def _shrunk_mean(self, local_mean, amount, global_mean, k=8):
        if amount <= 0:
            return global_mean

        return ((amount / (amount + k)) * local_mean) + ((k / (amount + k)) * global_mean)

    def _get_global_mean(self, stat_name):
        count = self.global_stat_counts.get(stat_name, 0)

        if count == 0:
            return self._get_default_stat_mean(stat_name)

        return self.global_stat_sums.get(stat_name, 0.0) / count

    def _get_default_stat_mean(self, stat_name):
        defaults = {
            "r": 1.0,
            "acs": 200.0,
            "kast": 70.0,
            "adr": 130.0,
            "hs": 25.0,
            "fpm": 0.0,
            "kd": 1.0,
            "fkfd": 1.0,
            "a": 5.0,
        }

        return defaults.get(stat_name, 0.0)

    def _add_distribution_features(self, features, name, values):
        features[name + "_mean"] = self._mean(values)
        features[name + "_median"] = self._median(values)
        features[name + "_min"] = min(values) if values else 0.0
        features[name + "_max"] = max(values) if values else 0.0
        features[name + "_std"] = self._std(values)

    def _count_recent_matches(self, date_times, date_time, days):
        count = 0

        for previous_date_time in date_times:
            age_days = (date_time - previous_date_time).total_seconds() / 86400

            if 0 <= age_days <= days:
                count += 1

        return count

    def _top_share(self, values, amount):
        positive_values = [value for value in values if value > 0]

        if not positive_values:
            return 0.0

        return sum(sorted(positive_values, reverse=True)[:amount]) / sum(positive_values)

    def _bottom_average(self, values, amount):
        if not values:
            return 0.0

        return self._mean(sorted(values)[:amount])

    def _to_float_or_none(self, value):
        try:
            value = str(value).replace("%", "").replace("+", "").strip()

            if value in ("", "-", "None"):
                return None

            return float(value)
        except (TypeError, ValueError):
            return None

    def _safe_divide(self, numerator, denominator):
        if denominator == 0:
            return 0.0

        return numerator / denominator

    def _mean(self, values):
        values = [value for value in values if value is not None]

        if not values:
            return 0.0

        return sum(values) / len(values)

    def _median(self, values):
        values = [value for value in values if value is not None]

        if not values:
            return 0.0

        return statistics.median(values)

    def _std(self, values):
        values = [value for value in values if value is not None]

        if len(values) < 2:
            return 0.0

        return statistics.pstdev(values)

    def _get_index_or_zero(self, values, index):
        if index >= len(values):
            return 0.0

        return values[index]


# FeatureBuilder
class FeatureBuilder:
    def __init__(self, state=None):
        self.state = state or FeatureState()

    def build_match_features(self, team_1_player_ids, team_2_player_ids, date_time=None, include_diagnostics=True):
        date_time = date_time or datetime.now()
        team_1_features = self.state.build_team_features(team_1_player_ids, date_time)
        team_2_features = self.state.build_team_features(team_2_player_ids, date_time)
        row = {}

        self._add_team_features(row, "team_1", team_1_features, include_diagnostics)
        self._add_team_features(row, "team_2", team_2_features, include_diagnostics)
        self._add_relative_features(row, team_1_features, team_2_features)

        return row

    def fit_matches(self, matches, get_match_date_time):
        matches = sorted(matches, key=get_match_date_time)
        pending_updates = []
        current_date_time = None

        for match in matches:
            match_date_time = get_match_date_time(match)

            if current_date_time is None:
                current_date_time = match_date_time

            if match_date_time != current_date_time:
                self._apply_pending_updates(pending_updates)
                pending_updates = []
                current_date_time = match_date_time

            pending_updates.append(self.state.create_match_update(match, match_date_time))

        self._apply_pending_updates(pending_updates)
        return self

    def _add_team_features(self, row, team, features, include_diagnostics):
        for name, value in features.items():
            if not include_diagnostics and isinstance(value, list):
                continue

            row[team + "_" + name] = value

    def _add_relative_features(self, row, team_1_features, team_2_features):
        for name, team_1_value in team_1_features.items():
            team_2_value = team_2_features.get(name)

            if not self._is_number(team_1_value) or not self._is_number(team_2_value):
                continue

            row["delta_" + name] = team_1_value - team_2_value
            row["sum_" + name] = team_1_value + team_2_value

    def _apply_pending_updates(self, pending_updates):
        for update in pending_updates:
            self.state.apply_update(update)

    def _is_number(self, value):
        return isinstance(value, (int, float)) and math.isfinite(value)
