"""Country-code normalization shared by serving and presentation layers."""
from __future__ import annotations

# Tennis feeds mix ISO-2, ISO-3 and IOC-style codes. Keep this explicit rather
# than guessing from names. Extend only with verified mappings.
ALPHA3_TO2 = {
    "ALB":"AL","ARG":"AR","AUS":"AU","AUT":"AT","BEL":"BE","BGR":"BG",
    "BIH":"BA","BLR":"BY","BRA":"BR","CAN":"CA","CHE":"CH","CHL":"CL",
    "CHN":"CN","COL":"CO","CRO":"HR","CZE":"CZ","DEU":"DE","DEN":"DK",
    "DOM":"DO","ECU":"EC","EGY":"EG","ESP":"ES","EST":"EE","FIN":"FI",
    "FRA":"FR","GBR":"GB","GEO":"GE","GRC":"GR","HKG":"HK","HUN":"HU",
    "IDN":"ID","IND":"IN","IRL":"IE","IRN":"IR","ISR":"IL","ITA":"IT",
    "JPN":"JP","KAZ":"KZ","KOR":"KR","LBN":"LB","LTU":"LT","LUX":"LU",
    "LVA":"LV","MAR":"MA","MDA":"MD","MEX":"MX","MKD":"MK","MNE":"ME",
    "NLD":"NL","NOR":"NO","NZL":"NZ","PER":"PE","PHL":"PH","POL":"PL",
    "PRT":"PT","ROU":"RO","RUS":"RU","SAU":"SA","SRB":"RS","SVK":"SK",
    "SVN":"SI","SWE":"SE","THA":"TH","TUN":"TN","TUR":"TR","TPE":"TW",
    "TWN":"TW","UKR":"UA","URY":"UY","USA":"US","UZB":"UZ","VEN":"VE",
    "ZAF":"ZA",
}
# Common IOC/provider aliases that are not ISO-3166 alpha-3. Tennis feeds
# frequently use these codes in player payloads. Values remain explicit so we
# never guess a country from a player name.
PROVIDER_TO2 = {
    "BAH":"BS", "BAR":"BB", "BER":"BM", "BUL":"BG", "CHI":"CL",
    "CRC":"CR", "CRO":"HR", "CYP":"CY", "ENG":"GB", "ESA":"SV",
    "GER":"DE", "GRE":"GR", "GUA":"GT", "INA":"ID", "ISL":"IS",
    "LAT":"LV", "MAS":"MY", "NED":"NL", "NIR":"GB", "PAR":"PY",
    "POR":"PT", "PUR":"PR", "ROM":"RO", "RSA":"ZA", "SCO":"GB",
    "SLO":"SI", "SUI":"CH", "URU":"UY", "VIE":"VN", "WAL":"GB",
}

# Open-Meteo venue resolution returns canonical country *names* rather than
# ISO codes. These aliases are explicit presentation/environment mappings, not
# player-name guesses. They are safe for venue/master normalization.
COUNTRY_NAME_TO2 = {
    "albania":"AL","argentina":"AR","australia":"AU","austria":"AT",
    "belarus":"BY","belgium":"BE","bolivia":"BO","bosnia and herzegovina":"BA",
    "brazil":"BR","bulgaria":"BG","canada":"CA","chile":"CL","china":"CN",
    "colombia":"CO","costa rica":"CR","croatia":"HR","cyprus":"CY",
    "czechia":"CZ","czech republic":"CZ","denmark":"DK","dominican republic":"DO",
    "ecuador":"EC","egypt":"EG","el salvador":"SV","estonia":"EE","finland":"FI",
    "france":"FR","georgia":"GE","germany":"DE","greece":"GR","hong kong":"HK",
    "hungary":"HU","iceland":"IS","india":"IN","indonesia":"ID","ireland":"IE",
    "israel":"IL","italy":"IT","japan":"JP","kazakhstan":"KZ","latvia":"LV",
    "lebanon":"LB","lithuania":"LT","luxembourg":"LU","malaysia":"MY",
    "mexico":"MX","moldova":"MD","republic of moldova":"MD","monaco":"MC",
    "montenegro":"ME","morocco":"MA","netherlands":"NL","new zealand":"NZ",
    "north macedonia":"MK","norway":"NO","paraguay":"PY","peru":"PE",
    "philippines":"PH","poland":"PL","portugal":"PT","puerto rico":"PR",
    "romania":"RO","russia":"RU","russian federation":"RU","saudi arabia":"SA",
    "serbia":"RS","singapore":"SG","slovakia":"SK","slovenia":"SI",
    "south africa":"ZA","south korea":"KR","republic of korea":"KR","korea, republic of":"KR",
    "spain":"ES","sweden":"SE","switzerland":"CH","taiwan":"TW",
    "taiwan, province of china":"TW","thailand":"TH","tunisia":"TN","turkey":"TR",
    "turkiye":"TR","türkiye":"TR","ukraine":"UA","united arab emirates":"AE",
    "united kingdom":"GB","great britain":"GB","england":"GB","scotland":"GB",
    "united states":"US","united states of america":"US","uruguay":"UY",
    "uzbekistan":"UZ","venezuela":"VE","vietnam":"VN","viet nam":"VN",
    "bahrain":"BH","barbados":"BB","bermuda":"BM","guatemala":"GT",
    "qatar":"QA","panama":"PA","jamaica":"JM","trinidad and tobago":"TT",
    "armenia":"AM","azerbaijan":"AZ","kyrgyzstan":"KG","tajikistan":"TJ",
}


def normalize_country_code(value: object) -> str:
    """Return an uppercase ISO-3166 alpha-2 code or an empty string."""
    raw = str(value or "").strip()
    code = raw.upper()
    if len(code) == 2 and code.isalpha():
        return code
    if len(code) == 3 and code.isalpha():
        found = ALPHA3_TO2.get(code) or PROVIDER_TO2.get(code, "")
        if found:
            return found
    # Country names here come from explicit provider/geocoder country fields.
    # Never call this function with a player or tournament *name* as a proxy.
    name = raw.casefold().replace("’", "'")
    return COUNTRY_NAME_TO2.get(name, "")
