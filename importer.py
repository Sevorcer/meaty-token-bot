import json
import os
from pathlib import Path

import psycopg

EXPORT_DIR = Path("received_exports")
DATABASE_URL = os.getenv("DATABASE_URL")


def get_conn():
    if DATABASE_URL:
        return psycopg.connect(DATABASE_URL)
    raise RuntimeError("DATABASE_URL is not set. Set it before running the importer.")


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                team_id BIGINT PRIMARY KEY,
                team_name TEXT,
                conference_name TEXT,
                division_name TEXT,
                team_ovr INTEGER
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS standings (
                team_id BIGINT PRIMARY KEY,
                wins INTEGER,
                losses INTEGER,
                ties INTEGER,
                win_pct DOUBLE PRECISION,
                seed INTEGER,
                pts_for INTEGER,
                pts_against INTEGER,
                turnover_diff INTEGER,
                off_total_yds_rank INTEGER,
                def_total_yds_rank INTEGER,
                FOREIGN KEY(team_id) REFERENCES teams(team_id)
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS players (
                roster_id BIGINT PRIMARY KEY,
                team_id BIGINT,
                first_name TEXT,
                last_name TEXT,
                full_name TEXT,
                position TEXT,
                age INTEGER,
                overall_rating INTEGER,
                jersey_num INTEGER,
                years_pro INTEGER,
                height INTEGER,
                weight INTEGER,
                college TEXT,
                player_best_ovr INTEGER,
                contract_salary BIGINT,
                contract_years_left INTEGER,
                is_free_agent INTEGER,
                injury_rating INTEGER,
                speed_rating INTEGER,
                strength_rating INTEGER,
                awareness_rating INTEGER,
                throw_power_rating INTEGER,
                break_tackle_rating INTEGER,
                man_cover_rating INTEGER,
                zone_cover_rating INTEGER,
                catch_rating INTEGER,
                carrying_rating INTEGER,
                rookie_year INTEGER,
                FOREIGN KEY(team_id) REFERENCES teams(team_id)
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS games (
                game_id BIGINT PRIMARY KEY,
                season_index INTEGER,
                stage_index INTEGER,
                week INTEGER,
                away_team_id BIGINT,
                home_team_id BIGINT,
                away_score INTEGER,
                home_score INTEGER,
                status INTEGER,
                is_game_of_the_week INTEGER DEFAULT 0,
                FOREIGN KEY(away_team_id) REFERENCES teams(team_id),
                FOREIGN KEY(home_team_id) REFERENCES teams(team_id)
            )
            """)
        conn.commit()


def load_json_file(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_latest_file(keyword: str):
    matches = sorted(
        EXPORT_DIR.glob(f"*{keyword}*.txt"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def find_all_files(keyword: str):
    return sorted(
        EXPORT_DIR.glob(f"*{keyword}*.txt"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def import_standings_file(path: Path):
    data = load_json_file(path)
    standings_list = data.get("content", {}).get("teamStandingInfoList", [])

    if not standings_list:
        print(f"No standings data found in {path.name}")
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            for team in standings_list:
                team_id = team.get("teamId")
                if team_id is None:
                    continue

                cur.execute("""
                    INSERT INTO teams (
                        team_id, team_name, conference_name, division_name, team_ovr
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (team_id) DO UPDATE SET
                        team_name = EXCLUDED.team_name,
                        conference_name = EXCLUDED.conference_name,
                        division_name = EXCLUDED.division_name,
                        team_ovr = EXCLUDED.team_ovr
                """, (
                    team_id,
                    team.get("teamName"),
                    team.get("conferenceName"),
                    team.get("divisionName"),
                    team.get("teamOvr"),
                ))

                cur.execute("""
                    INSERT INTO standings (
                        team_id, wins, losses, ties, win_pct, seed,
                        pts_for, pts_against, turnover_diff,
                        off_total_yds_rank, def_total_yds_rank
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (team_id) DO UPDATE SET
                        wins = EXCLUDED.wins,
                        losses = EXCLUDED.losses,
                        ties = EXCLUDED.ties,
                        win_pct = EXCLUDED.win_pct,
                        seed = EXCLUDED.seed,
                        pts_for = EXCLUDED.pts_for,
                        pts_against = EXCLUDED.pts_against,
                        turnover_diff = EXCLUDED.turnover_diff,
                        off_total_yds_rank = EXCLUDED.off_total_yds_rank,
                        def_total_yds_rank = EXCLUDED.def_total_yds_rank
                """, (
                    team_id,
                    team.get("totalWins", 0),
                    team.get("totalLosses", 0),
                    team.get("totalTies", 0),
                    team.get("winPct", 0.0),
                    team.get("seed", 0),
                    team.get("ptsFor", 0),
                    team.get("ptsAgainst", 0),
                    team.get("tODiff", 0),
                    team.get("offTotalYdsRank", 0),
                    team.get("defTotalYdsRank", 0),
                ))
        conn.commit()

    print(f"Imported standings from {path.name}")


def import_roster_file(path: Path):
    data = load_json_file(path)
    roster_list = data.get("content", {}).get("rosterInfoList", [])

    if not roster_list:
        print(f"No roster data found in {path.name}")
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            for player in roster_list:
                roster_id = player.get("rosterId")
                if roster_id is None:
                    continue

                first_name = player.get("firstName", "")
                last_name = player.get("lastName", "")
                full_name = f"{first_name} {last_name}".strip()

                cur.execute("""
                    INSERT INTO players (
                        roster_id, team_id, first_name, last_name, full_name,
                        position, age, overall_rating, jersey_num, years_pro,
                        height, weight, college, player_best_ovr,
                        contract_salary, contract_years_left, is_free_agent,
                        injury_rating, speed_rating, strength_rating,
                        awareness_rating, throw_power_rating, break_tackle_rating,
                        man_cover_rating, zone_cover_rating, catch_rating,
                        carrying_rating, rookie_year
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (roster_id) DO UPDATE SET
                        team_id = EXCLUDED.team_id,
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        full_name = EXCLUDED.full_name,
                        position = EXCLUDED.position,
                        age = EXCLUDED.age,
                        overall_rating = EXCLUDED.overall_rating,
                        jersey_num = EXCLUDED.jersey_num,
                        years_pro = EXCLUDED.years_pro,
                        height = EXCLUDED.height,
                        weight = EXCLUDED.weight,
                        college = EXCLUDED.college,
                        player_best_ovr = EXCLUDED.player_best_ovr,
                        contract_salary = EXCLUDED.contract_salary,
                        contract_years_left = EXCLUDED.contract_years_left,
                        is_free_agent = EXCLUDED.is_free_agent,
                        injury_rating = EXCLUDED.injury_rating,
                        speed_rating = EXCLUDED.speed_rating,
                        strength_rating = EXCLUDED.strength_rating,
                        awareness_rating = EXCLUDED.awareness_rating,
                        throw_power_rating = EXCLUDED.throw_power_rating,
                        break_tackle_rating = EXCLUDED.break_tackle_rating,
                        man_cover_rating = EXCLUDED.man_cover_rating,
                        zone_cover_rating = EXCLUDED.zone_cover_rating,
                        catch_rating = EXCLUDED.catch_rating,
                        carrying_rating = EXCLUDED.carrying_rating,
                        rookie_year = EXCLUDED.rookie_year
                """, (
                    roster_id,
                    player.get("teamId"),
                    first_name,
                    last_name,
                    full_name,
                    player.get("position"),
                    player.get("age"),
                    player.get("overallRating"),
                    player.get("jerseyNum"),
                    player.get("yearsPro"),
                    player.get("height"),
                    player.get("weight"),
                    player.get("college"),
                    player.get("playerBestOvr"),
                    player.get("contractSalary"),
                    player.get("contractYearsLeft"),
                    1 if player.get("isFreeAgent") else 0,
                    player.get("injuryRating"),
                    player.get("speedRating"),
                    player.get("strengthRating"),
                    player.get("awarenessRating"),
                    player.get("throwPowerRating"),
                    player.get("breakTackleRating"),
                    player.get("manCoverRating"),
                    player.get("zoneCoverRating"),
                    player.get("catchRating"),
                    player.get("carryingRating"),
                    player.get("rookieYear"),
                ))
        conn.commit()

    print(f"Imported roster from {path.name}")


def import_schedule_file(path: Path):
    data = load_json_file(path)
    schedule_list = data.get("content", {}).get("gameScheduleInfoList", [])

    if not schedule_list:
        print(f"No schedule data found in {path.name}")
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            for game in schedule_list:
                game_id = game.get("scheduleId")
                if game_id is None:
                    continue

                cur.execute("""
                    INSERT INTO games (
                        game_id,
                        season_index,
                        stage_index,
                        week,
                        away_team_id,
                        home_team_id,
                        away_score,
                        home_score,
                        status,
                        is_game_of_the_week
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (game_id) DO UPDATE SET
                        season_index = EXCLUDED.season_index,
                        stage_index = EXCLUDED.stage_index,
                        week = EXCLUDED.week,
                        away_team_id = EXCLUDED.away_team_id,
                        home_team_id = EXCLUDED.home_team_id,
                        away_score = EXCLUDED.away_score,
                        home_score = EXCLUDED.home_score,
                        status = EXCLUDED.status,
                        is_game_of_the_week = EXCLUDED.is_game_of_the_week
                """, (
                    game.get("scheduleId"),
                    game.get("seasonIndex"),
                    game.get("stageIndex"),
                    game.get("weekIndex"),
                    game.get("awayTeamId"),
                    game.get("homeTeamId"),
                    game.get("awayScore", 0),
                    game.get("homeScore", 0),
                    game.get("status"),
                    1 if game.get("isGameOfTheWeek") else 0,
                ))
        conn.commit()

    print(f"Imported schedule from {path.name}")


def main():
    init_db()

    standings_file = find_latest_file("standings")
    roster_files = find_all_files("roster")
    schedule_file = find_latest_file("schedule")

    if standings_file:
        try:
            import_standings_file(standings_file)
        except Exception as exc:
            print(f"Failed to import standings from {standings_file.name}: {exc}")
    else:
        print("No standings file found.")

    if roster_files:
        print(f"Found {len(roster_files)} roster files.")
        for roster_file in roster_files:
            try:
                import_roster_file(roster_file)
            except Exception as exc:
                print(f"Failed to import roster from {roster_file.name}: {exc}")
    else:
        print("No roster files found.")

    if schedule_file:
        try:
            import_schedule_file(schedule_file)
        except Exception as exc:
            print(f"Failed to import schedule from {schedule_file.name}: {exc}")
    else:
        print("No schedule file found.")

    print("Import complete.")


if __name__ == "__main__":
    main()
