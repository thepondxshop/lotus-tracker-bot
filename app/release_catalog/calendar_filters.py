"""Calendar edition filters; region and language are independent."""
def filter_editions(entries, region='ALL', language='ALL'):
    region, language = region.strip().upper(), language.strip().casefold()
    return [e for e in entries
            if (region == 'ALL' or str(e.get('region', '')).upper() == region)
            and (language == 'all' or str(e.get('language', '')).casefold() == language)]
