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


def normalize_country_code(value: object) -> str:
    """Return an uppercase ISO-3166 alpha-2 code or an empty string."""
    code = str(value or "").strip().upper()
    if len(code) == 2 and code.isalpha():
        return code
    if len(code) == 3 and code.isalpha():
        return ALPHA3_TO2.get(code, "")
    return ""
