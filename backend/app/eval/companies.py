"""The 3 companies the pilot backtest covers (frozen Wayback dataset + ground_truth.yaml).

Used ONLY by the evaluation (app.eval.dataset / replay); the live app starts empty and tracks whatever
companies the user adds.
"""

BACKTEST_COMPANIES = [
    {
        "name": "Vercel",
        "domain": "vercel.com",
        "pricing_url": "https://vercel.com/pricing",
        "product_urls": ["https://vercel.com/", "https://vercel.com/changelog"],
        "careers_provider": "greenhouse",
        "careers_token": "vercel",
        "news_query": "Vercel",
        "feed_urls": ["https://vercel.com/atom"],
    },
    {
        "name": "Figma",
        "domain": "figma.com",
        "pricing_url": "https://www.figma.com/pricing/",
        "product_urls": ["https://www.figma.com/", "https://www.figma.com/release-notes/"],
        "careers_provider": "greenhouse",
        "careers_token": "figma",
        "news_query": "Figma",
        "feed_urls": ["https://www.figma.com/blog/feed/atom.xml"],
    },
    {
        "name": "Airtable",
        "domain": "airtable.com",
        "pricing_url": "https://www.airtable.com/pricing",
        "product_urls": ["https://www.airtable.com/"],
        "careers_provider": "greenhouse",
        "careers_token": "airtable",
        "news_query": "Airtable",
        "feed_urls": [],
    },
]
