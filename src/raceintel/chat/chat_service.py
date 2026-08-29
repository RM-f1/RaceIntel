
import re

from raceintel.chat.gemini import GeminiClient
from raceintel.chat.prompts import build_prompt
from raceintel.retrieval.retriever import Retriever


class ChatService:
    """
    Handles RaceIntel questions.

    Strategy:
    1. Retrieve grounded F1 data.
    2. Parse driver reports correctly.
    3. Answer deterministic factual questions directly.
    4. Use Gemini only when generation is genuinely required.
    """

    def __init__(self):
        self.retriever = Retriever()
        self.llm = GeminiClient()

    # ============================================================
    # PARSING
    # ============================================================

    def _extract_driver_results(self, context: str):
        """
        Extract driver, position, points and team from RaceIntel
        driver reports.

        Handles the actual ChromaDB format:

        Driver:
        Charles Leclerc

        Constructor:
        Ferrari

        Finished:
        P1

        Points:
        25.0
        """

        results = []

        context = context.replace("\r\n", "\n").strip()

        # Split only when a NEW Driver section starts.
        sections = re.split(
            r"(?=^Driver:\s*$)",
            context,
            flags=re.IGNORECASE | re.MULTILINE
        )

        for section in sections:

            if not re.search(
                r"^Driver:\s*$",
                section,
                re.IGNORECASE | re.MULTILINE
            ):
                continue

            # ----------------------------------------------------
            # DRIVER
            # ----------------------------------------------------

            driver_match = re.search(
                r"^Driver:\s*$\s*(.+)",
                section,
                re.IGNORECASE | re.MULTILINE
            )

            if not driver_match:
                continue

            driver = driver_match.group(1).strip()

            # ----------------------------------------------------
            # TEAM / CONSTRUCTOR
            # ----------------------------------------------------

            team_match = re.search(
                r"^(?:Constructor|Team):\s*$\s*(.+)",
                section,
                re.IGNORECASE | re.MULTILINE
            )

            team = (
                team_match.group(1).strip()
                if team_match
                else None
            )

            # ----------------------------------------------------
            # FINISHING POSITION
            # ----------------------------------------------------

            position_match = re.search(
                r"^(?:Finished|Finishing Position|Finished Position):"
                r"\s*$\s*(P\d+|DNF|DNS)",
                section,
                re.IGNORECASE | re.MULTILINE
            )

            position = (
                position_match.group(1).upper()
                if position_match
                else None
            )

            # ----------------------------------------------------
            # POINTS
            # ----------------------------------------------------

            points_match = re.search(
                r"^Points(?:\s+Scored)?:"
                r"\s*$\s*([\d.]+)",
                section,
                re.IGNORECASE | re.MULTILINE
            )

            points = (
                float(points_match.group(1))
                if points_match
                else None
            )

            results.append(
                {
                    "driver": driver,
                    "position": position,
                    "points": points,
                    "team": team,
                }
            )

        return results

    # ============================================================
    # RACE REPORT PARSING
    # ============================================================

    def _extract_race_info(self, context: str):
        """
        Extract winner and podium information from race reports.
        """

        winner = None
        podium = []

        # Winner
        winner_match = re.search(
            r"Winner:\s*(?:\n\s*)?(.+)",
            context,
            re.IGNORECASE
        )

        if winner_match:
            winner = winner_match.group(1).strip()

        # Podium section
        podium_match = re.search(
            r"Podium:\s*(.*?)(?:\n\s*\n|Classification:|$)",
            context,
            re.IGNORECASE | re.DOTALL
        )

        if podium_match:

            podium_text = podium_match.group(1)

            podium_matches = re.findall(
                r"([123])\.\s*(.+)",
                podium_text
            )

            podium = [
                {
                    "position": f"P{position}",
                    "driver": driver.strip()
                }
                for position, driver in podium_matches
            ]

        return {
            "winner": winner,
            "podium": podium,
        }

    # ============================================================
    # DIRECT ANSWERS
    # ============================================================

    def _direct_answer(self, question: str, context: str):

        q = question.lower().strip()

        results = self._extract_driver_results(context)
        race_info = self._extract_race_info(context)

        print("\n========== PARSED RESULTS ==========")
        print(results)
        print("====================================")

        # ========================================================
        # 1. DRIVER PERFORMANCE
        # ========================================================

        if "how did" in q and "perform" in q:

            for result in results:

                if result["driver"].lower() in q:

                    if (
                        result["position"] is not None
                        and result["points"] is not None
                    ):
                        return (
                            f"{result['driver']} finished "
                            f"{result['position']} and scored "
                            f"{result['points']} points."
                        )

        # ========================================================
        # 2. HOW MANY POINTS DID DRIVER SCORE?
        # ========================================================

        if (
            "how many points" in q
            or "how much points" in q
        ):

            for result in results:

                if result["driver"].lower() in q:

                    if result["points"] is not None:

                        return (
                            f"{result['driver']} scored "
                            f"{result['points']} points."
                        )

        # ========================================================
        # 3. WHAT POSITION DID DRIVER FINISH?
        # ========================================================

        if (
            "what position" in q
            or "which position" in q
            or "position did" in q
        ):

            for result in results:

                if result["driver"].lower() in q:

                    if result["position"]:

                        return (
                            f"{result['driver']} finished "
                            f"{result['position']}."
                        )

        # ========================================================
        # 4. WHO WON?
        # ========================================================

        if (
            "who won" in q
            or "which driver won" in q
        ):

            # First use race report winner.
            if race_info["winner"]:

                return f"{race_info['winner']} won the race."

            # Fallback to driver reports.
            for result in results:

                if result["position"] == "P1":

                    return (
                        f"{result['driver']} won the race."
                    )

        # ========================================================
        # 5. WHO SCORED POINTS?
        # ========================================================

        if "who scored points" in q:

            scored = [
                r
                for r in results
                if (
                    r["points"] is not None
                    and r["points"] > 0
                )
            ]

            if scored:

                return "\n".join(
                    f"{r['driver']}: {r['points']} points"
                    for r in scored
                )

        # ========================================================
        # 6. WHO FINISHED ON THE PODIUM?
        # ========================================================

        if "podium" in q:

            # Race report podium is the most reliable source.
            if race_info["podium"]:

                return "\n".join(
                    f"{p['position']}. {p['driver']}"
                    for p in race_info["podium"]
                )

            # Fallback to driver reports.
            podium = [
                r
                for r in results
                if (
                    r["position"] is not None
                    and r["position"] in {
                        "P1",
                        "P2",
                        "P3"
                    }
                )
            ]

            if podium:

                podium.sort(
                    key=lambda r: int(
                        r["position"][1:]
                    )
                )

                return "\n".join(
                    f"{r['position']}. {r['driver']}"
                    for r in podium
                )

        # ========================================================
        # 7. WHICH DRIVER FINISHED HIGHER?
        # ========================================================

        if "finished higher" in q:

            # IMPORTANT:
            # If the question mentions a team, restrict results
            # to that team before comparing positions.

            team_names = {
                "ferrari": "Ferrari",
                "mercedes": "Mercedes",
                "mclaren": "McLaren",
                "red bull": "Red Bull Racing",
                "aston martin": "Aston Martin",
                "alpine": "Alpine",
                "haas": "Haas",
                "williams": "Williams",
                "rb": "RB",
                "sauber": "Kick Sauber",
            }

            selected_team = None

            for name, team in team_names.items():

                if name in q:

                    selected_team = team
                    break

            if selected_team:

                team_results = [
                    r
                    for r in results
                    if r["team"] == selected_team
                ]

                if team_results:

                    valid_results = [
                        r
                        for r in team_results
                        if (
                            r["position"] is not None
                            and r["position"].startswith("P")
                        )
                    ]

                    if valid_results:

                        valid_results.sort(
                            key=lambda r: int(
                                r["position"][1:]
                            )
                        )

                        return valid_results[0]["driver"]

            # Generic fallback.
            valid_results = [
                r
                for r in results
                if (
                    r["position"] is not None
                    and r["position"].startswith("P")
                )
            ]

            if valid_results:

                valid_results.sort(
                    key=lambda r: int(
                        r["position"][1:]
                    )
                )

                return valid_results[0]["driver"]

        # ========================================================
        # 8. WHO SCORED THE MOST POINTS?
        # ========================================================

        if "most points" in q:

            team_names = {
                "ferrari": "Ferrari",
                "mercedes": "Mercedes",
                "mclaren": "McLaren",
                "red bull": "Red Bull Racing",
                "aston martin": "Aston Martin",
                "alpine": "Alpine",
                "haas": "Haas",
                "williams": "Williams",
                "rb": "RB",
                "sauber": "Kick Sauber",
            }

            selected_team = None

            for name, team in team_names.items():

                if name in q:

                    selected_team = team
                    break

            candidates = results

            if selected_team:

                candidates = [
                    r
                    for r in results
                    if r["team"] == selected_team
                ]

            candidates = [
                r
                for r in candidates
                if r["points"] is not None
            ]

            if candidates:

                best = max(
                    candidates,
                    key=lambda r: r["points"]
                )

                return best["driver"]

        # ========================================================
        # 9. TEAM RESULT / TEAM PERFORMANCE
        # ========================================================

        team_keywords = {
            "ferrari": "Ferrari",
            "mercedes": "Mercedes",
            "mclaren": "McLaren",
            "red bull": "Red Bull Racing",
            "aston martin": "Aston Martin",
            "alpine": "Alpine",
            "haas": "Haas",
            "williams": "Williams",
            "rb": "RB",
            "sauber": "Kick Sauber",
        }

        selected_team = None

        for name, team in team_keywords.items():

            if name in q:

                selected_team = team
                break

        if selected_team:

            team_results = [
                r
                for r in results
                if r["team"] == selected_team
            ]

            if team_results:

                team_results.sort(
                    key=lambda r: (
                        int(r["position"][1:])
                        if (
                            r["position"]
                            and r["position"].startswith("P")
                        )
                        else 999
                    )
                )

                return "\n".join(
                    f"{r['driver']}: "
                    f"{r['position']}, "
                    f"{r['points']} points"
                    for r in team_results
                )

        return None

    # ============================================================
    # ASK
    # ============================================================

    def ask(self, question: str) -> str:

        print("\n========================================")
        print("RACEINTEL CHAT")
        print("========================================")
        print("Question:", question)

        # --------------------------------------------------------
        # RETRIEVE
        # --------------------------------------------------------

        context = self.retriever.retrieve(question)

        print("\n========== CONTEXT ==========")
        print(context[:3000])
        print("=============================")

        # --------------------------------------------------------
        # DIRECT ANSWER
        # --------------------------------------------------------

        direct_answer = self._direct_answer(
            question,
            context
        )

        if direct_answer is not None:

            print(
                "\n========== DIRECT ANSWER =========="
            )

            print(direct_answer)

            print(
                "===================================\n"
            )

            return direct_answer

        # --------------------------------------------------------
        # GEMINI FALLBACK
        # --------------------------------------------------------

        print(
            "\n========== GEMINI FALLBACK =========="
        )

        prompt = build_prompt(
            question,
            context
        )

        return self.llm.generate(prompt)
