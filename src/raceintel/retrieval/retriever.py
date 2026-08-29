from raceintel.retrieval.chroma_client import ChromaClient


class Retriever:
    """
    Retrieves relevant F1 documents from ChromaDB.

    Deterministic retrieval is used whenever the question contains
    enough information to identify the required race, driver, or team.
    """

    RACES = {
        "bahrain": "Bahrain Grand Prix",
        "saudi": "Saudi Arabian Grand Prix",
        "saudi arabia": "Saudi Arabian Grand Prix",
        "australia": "Australian Grand Prix",
        "australian": "Australian Grand Prix",
        "japan": "Japanese Grand Prix",
        "japanese": "Japanese Grand Prix",
        "china": "Chinese Grand Prix",
        "chinese": "Chinese Grand Prix",
        "miami": "Miami Grand Prix",
        "emilia": "Emilia Romagna Grand Prix",
        "imola": "Emilia Romagna Grand Prix",
        "monaco": "Monaco Grand Prix",
        "canada": "Canadian Grand Prix",
        "canadian": "Canadian Grand Prix",
        "spain": "Spanish Grand Prix",
        "spanish": "Spanish Grand Prix",
        "austria": "Austrian Grand Prix",
        "austrian": "Austrian Grand Prix",
        "britain": "British Grand Prix",
        "british": "British Grand Prix",
        "hungary": "Hungarian Grand Prix",
        "hungarian": "Hungarian Grand Prix",
        "belgium": "Belgian Grand Prix",
        "belgian": "Belgian Grand Prix",
        "netherlands": "Dutch Grand Prix",
        "dutch": "Dutch Grand Prix",
        "italy": "Italian Grand Prix",
        "italian": "Italian Grand Prix",
        "azerbaijan": "Azerbaijan Grand Prix",
        "singapore": "Singapore Grand Prix",
        "usa": "United States Grand Prix",
        "united states": "United States Grand Prix",
        "austin": "United States Grand Prix",
        "mexico": "Mexico City Grand Prix",
        "mexican": "Mexico City Grand Prix",
        "brazil": "São Paulo Grand Prix",
        "sao paulo": "São Paulo Grand Prix",
        "são paulo": "São Paulo Grand Prix",
        "las vegas": "Las Vegas Grand Prix",
        "qatar": "Qatar Grand Prix",
        "abu dhabi": "Abu Dhabi Grand Prix",
    }

    DRIVERS = {
        "max verstappen": "Max Verstappen",
        "verstappen": "Max Verstappen",
        "max": "Max Verstappen",

        "sergio perez": "Sergio Perez",
        "perez": "Sergio Perez",
        "checo": "Sergio Perez",

        "charles leclerc": "Charles Leclerc",
        "leclerc": "Charles Leclerc",

        "carlos sainz": "Carlos Sainz",
        "sainz": "Carlos Sainz",

        "lewis hamilton": "Lewis Hamilton",
        "hamilton": "Lewis Hamilton",

        "george russell": "George Russell",
        "russell": "George Russell",

        "lando norris": "Lando Norris",
        "norris": "Lando Norris",

        "oscar piastri": "Oscar Piastri",
        "piastri": "Oscar Piastri",

        "fernando alonso": "Fernando Alonso",
        "alonso": "Fernando Alonso",

        "lance stroll": "Lance Stroll",
        "stroll": "Lance Stroll",

        "pierre gasly": "Pierre Gasly",
        "gasly": "Pierre Gasly",

        "esteban ocon": "Esteban Ocon",
        "ocon": "Esteban Ocon",

        "yuki tsunoda": "Yuki Tsunoda",
        "tsunoda": "Yuki Tsunoda",

        "daniel ricciardo": "Daniel Ricciardo",
        "ricciardo": "Daniel Ricciardo",

        "alex albon": "Alex Albon",
        "albon": "Alex Albon",

        "logan sargeant": "Logan Sargeant",
        "sargeant": "Logan Sargeant",

        "nico hulkenberg": "Nico Hulkenberg",
        "hulkenberg": "Nico Hulkenberg",

        "kevin magnussen": "Kevin Magnussen",
        "magnussen": "Kevin Magnussen",
        "kevin": "Kevin Magnussen",

        "valtteri bottas": "Valtteri Bottas",
        "bottas": "Valtteri Bottas",

        "zhou guanyu": "Zhou Guanyu",
        "zhou": "Zhou Guanyu",
    }

    TEAMS = {
        "red bull racing": "Red Bull Racing",
        "red bull": "Red Bull Racing",

        "ferrari": "Ferrari",
        "mercedes": "Mercedes",
        "mclaren": "McLaren",
        "aston martin": "Aston Martin",
        "alpine": "Alpine",
        "haas": "Haas",
        "williams": "Williams",

        "visa cash app rb": "RB",
        "rb": "RB",

        "kick sauber": "Kick Sauber",
        "sauber": "Kick Sauber",
    }

    DRIVER_KEYWORDS = {
        "driver",
        "finish",
        "finished",
        "position",
        "points",
        "constructor",
        "team",
        "performed",
        "performance",
        "grid",
    }

    def __init__(self):
        self.client = ChromaClient()

    # ============================================================
    # FILTER EXTRACTION
    # ============================================================

    def _extract_filters(self, question: str) -> dict:
        """
        Extract race, driver, team and season information.
        """

        q = question.lower().strip()

        filters = {}

        # --------------------------------------------------------
        # Season
        # --------------------------------------------------------

        if "2024" in q:
            filters["season"] = 2024

        # --------------------------------------------------------
        # Race
        #
        # Sort by length so "abu dhabi" is checked before
        # shorter possible matches.
        # --------------------------------------------------------

        for keyword in sorted(
            self.RACES.keys(),
            key=len,
            reverse=True
        ):
            if keyword in q:
                filters["race_name"] = self.RACES[keyword]
                break

        # --------------------------------------------------------
        # Driver
        # --------------------------------------------------------

        for keyword in sorted(
            self.DRIVERS.keys(),
            key=len,
            reverse=True
        ):
            if keyword in q:
                filters["driver"] = self.DRIVERS[keyword]
                break

        # --------------------------------------------------------
        # Team
        # --------------------------------------------------------

        for keyword in sorted(
            self.TEAMS.keys(),
            key=len,
            reverse=True
        ):
            if keyword in q:
                filters["team"] = self.TEAMS[keyword]
                break

        # --------------------------------------------------------
        # Document type
        # --------------------------------------------------------

        if "team" in filters or "driver" in filters:
            filters["document_type"] = "driver_report"

        elif any(
            keyword in q
            for keyword in self.DRIVER_KEYWORDS
        ):
            filters["document_type"] = "driver_report"

        else:
            filters["document_type"] = "race_report"

        return filters

    # ============================================================
    # CHROMA WHERE BUILDER
    # ============================================================

    def _build_where(self, filters: dict) -> dict:
        """
        Convert metadata filters into a ChromaDB where clause.
        """

        if not filters:
            return {}

        if len(filters) == 1:
            return filters

        return {
            "$and": [
                {key: value}
                for key, value in filters.items()
            ]
        }

    # ============================================================
    # DRIVER REPORT RETRIEVAL
    # ============================================================

    def _get_driver_reports(
        self,
        race_name: str,
        driver: str | None = None,
        team: str | None = None,
    ):
        """
        Retrieve driver reports for a race.

        If driver is supplied, return that driver.

        If team is supplied, return ALL drivers belonging
        to that team.

        Otherwise return all drivers for the race.
        """

        conditions = [
            {"race_name": race_name},
            {"document_type": "driver_report"},
        ]

        if driver:
            conditions.append(
                {"driver": driver}
            )

        if team:
            conditions.append(
                {"team": team}
            )

        where = {
            "$and": conditions
        }

        results = self.client.collection.get(
            where=where,
            include=[
                "documents",
                "metadatas",
            ],
        )

        return results

    # ============================================================
    # RACE REPORT RETRIEVAL
    # ============================================================

    def _get_race_report(self, race_name: str):
        """
        Retrieve the race report for a specific Grand Prix.
        """

        results = self.client.collection.get(
            where={
                "$and": [
                    {
                        "race_name": race_name
                    },
                    {
                        "document_type": "race_report"
                    },
                ]
            },
            include=[
                "documents",
                "metadatas",
            ],
        )

        documents = results.get(
            "documents",
            []
        )

        return "\n\n".join(documents)

    # ============================================================
    # MAIN RETRIEVAL
    # ============================================================

    def retrieve(
        self,
        question: str,
        n_results: int = 5,
    ) -> str:
        """
        Retrieve the best grounded context for the question.
        """

        filters = self._extract_filters(question)

        print("\n========== RETRIEVAL ==========")
        print("Question :", question)
        print("Filters  :", filters)
        print("===============================\n")

        race_name = filters.get(
            "race_name"
        )

        driver = filters.get(
            "driver"
        )

        team = filters.get(
            "team"
        )

        document_type = filters.get(
            "document_type"
        )

        # ========================================================
        # DETERMINISTIC DRIVER RETRIEVAL
        # ========================================================

        if (
            race_name
            and document_type == "driver_report"
            and driver
        ):

            results = self._get_driver_reports(
                race_name=race_name,
                driver=driver,
            )

            documents = results.get(
                "documents",
                []
            )

            context = "\n\n".join(
                documents
            )

            print(
                "Deterministic driver retrieval:"
            )
            print(context)

            return context

        # ========================================================
        # DETERMINISTIC TEAM RETRIEVAL
        # ========================================================

        if (
            race_name
            and document_type == "driver_report"
            and team
        ):

            results = self._get_driver_reports(
                race_name=race_name,
                team=team,
            )

            documents = results.get(
                "documents",
                []
            )

            metadatas = results.get(
                "metadatas",
                []
            )

            # Sort drivers consistently by driver name.
            combined = list(
                zip(
                    documents,
                    metadatas,
                )
            )

            combined.sort(
                key=lambda item: item[1].get(
                    "driver",
                    ""
                )
            )

            context_parts = []

            for document, metadata in combined:

                context_parts.append(
                    document
                )

            context = "\n\n".join(
                context_parts
            )

            print(
                "Deterministic team retrieval:"
            )
            print(context)

            return context

        # ========================================================
        # DETERMINISTIC ALL-DRIVER RETRIEVAL
        # ========================================================
        #
        # Handles questions like "Who scored points in Abu Dhabi?"
        # or "Who finished on the podium in Monaco?" — a race and
        # driver_report document type are known, but no specific
        # driver or team was named. _get_driver_reports() already
        # returns every driver report for the race in that case,
        # so use it instead of falling through to capped semantic
        # search.
        # ========================================================

        if (
            race_name
            and document_type == "driver_report"
            and not driver
            and not team
        ):

            results = self._get_driver_reports(
                race_name=race_name,
            )

            documents = results.get(
                "documents",
                []
            )

            metadatas = results.get(
                "metadatas",
                []
            )

            # Sort drivers consistently by driver name.
            combined = list(
                zip(
                    documents,
                    metadatas,
                )
            )

            combined.sort(
                key=lambda item: item[1].get(
                    "driver",
                    ""
                )
            )

            context = "\n\n".join(
                document
                for document, metadata in combined
            )

            print(
                "Deterministic all-driver retrieval:"
            )
            print(context)

            return context

        # ========================================================
        # DETERMINISTIC RACE RETRIEVAL
        # ========================================================

        if (
            race_name
            and document_type == "race_report"
        ):

            context = self._get_race_report(
                race_name
            )

            print(
                "Deterministic race retrieval:"
            )
            print(context)

            return context

        # ========================================================
        # FALLBACK SEMANTIC RETRIEVAL
        # ========================================================

        query_kwargs = {
            "query_texts": [question],
            "n_results": n_results,
        }

        where = self._build_where(
            filters
        )

        if where:
            query_kwargs["where"] = where

        print(
            "Semantic where clause:",
            where
        )

        results = self.client.collection.query(
            **query_kwargs
        )

        documents = results.get(
            "documents",
            [[]]
        )[0]

        return "\n\n".join(
            documents
        )