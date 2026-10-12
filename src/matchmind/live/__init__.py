"""The live pipeline: a simulated match arrives as a feed, is interpreted as it arrives, and gets its overlays written while it is still being played.

``store``     where the feed, the moments and the overlays live (memory for tests, Cosmos DB on Azure)
``feed``      the synthetic data provider: a simulated match released over time at a chosen speed
``pipeline``  the two stages in between (interpret new documents, write narrative overlays for new moments)
``simulator`` the command the Container Apps Job runs (``python -m matchmind.live.simulator``)
"""
