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


def normalize_country_code(value: object) -> str:
    """Return an uppercase ISO-3166 alpha-2 code or an empty string."""
    code = str(value or "").strip().upper()
    if len(code) == 2 and code.isalpha():
        return code
    if len(code) == 3 and code.isalpha():
        return ALPHA3_TO2.get(code) or PROVIDER_TO2.get(code, "")
    return ""
