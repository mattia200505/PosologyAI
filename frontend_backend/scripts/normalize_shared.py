"""
Normalisation des noms de médicaments / DCI.
Partagé entre matching_drugbank.py (index) et enrichment_service.py (runtime).
"""

import re
import unicodedata


def normalize(text: str) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    # Les apostrophes sont remplacées par une espace avant le repli ASCII.
    # Sans cela « chlorhydrate d’oxycodone » devient « chlorhydrate doxycodone »,
    # le « d » se collant au nom de la molécule et la rendant introuvable.
    text = re.sub(r"['’ʼ‘`]", ' ', text)
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
    text = re.sub(r'[^a-z0-9\s\-]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def normalize_dci(text: str) -> str:
    """Normalisation DCI : supprime dosages, formes pharmaceutiques, suffixes labo."""
    text = normalize(text)
    text = re.sub(r'\b\d+\s*(?:mg|g|ml|ui|%|pour\s*cent)\b', '', text, flags=re.IGNORECASE)
    text = re.sub(
        r'\b(comprime|comp|gelule|gele|sirop|solution|injectable|pommade|creme|'
        r'collyre|suppositoire|ampoule|suspension|poudre|pellicule|capsule|'
        r'comprim|gellule)\b',
        '', text, flags=re.IGNORECASE
    )
    text = re.sub(
        r'\b(sandoz|teva|arrow|biogaran|zydus|viatris|eg|evolugen|zentiva|'
        r'mylan|accord|cristers|laboratoire|lab|qualimed|mepha|pharmagenus|'
        r'generique|arrow generiques)\b',
        '', text, flags=re.IGNORECASE
    )
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ── Réduction des formes salifiées et estérifiées ─────────────────────
#
# DrugBank nomme la molécule ; l'ANSM nomme la forme réellement présente dans
# le comprimé. « Chlorhydrate de tramadol » et « tramadol » désignent le même
# principe actif, mais aucune comparaison de chaînes ne les rapproche.
#
# Mesuré sur les 3 336 échecs d'appariement porteurs d'une substance :
# 2 079 se résolvent (62,3 %) par cette seule réduction.

# Sels et esters placés en tête, suivis du génitif : « <sel> de <molécule> ».
_SELS = (
    r'(chlorhydrate|dichlorhydrate|bromhydrate|sulfate|hemisulfate|fumarate|'
    r'hemifumarate|maleate|tartrate|bitartrate|hydrogenotartrate|citrate|'
    r'acetate|phosphate|dihydrogenophosphate|succinate|hemisuccinate|nitrate|'
    r'chlorure|bromure|iodure|oxalate|benzoate|dipropionate|propionate|'
    r'valerate|furoate|pamoate|embonate|gluconate|lactate|malate|carbonate|'
    r'bicarbonate|stearate|palmitate|besilate|besylate|mesilate|mesylate|'
    r'tosilate|napadisilate|xinafoate|aceponate|butyrate|caproate|enantate|'
    r'decanoate|undecylate|trifluoroacetate|edisilate|'
    # Ajoutés le 12/08/2026 (P9-5) : relevés parmi les substances restées non
    # appariées. `hydroxyde` en est volontairement absent — le réduire ferait
    # de « hydroxyde d'aluminium » de l'aluminium élémentaire, faux
    # appariement que la garde `_MINERAUX` bloque de toute façon.
    r'dimesilate|dimesylate|isethionate|dinitrate|mononitrate|hemitartrate|'
    r'camsilate|camsylate|tosylate|orotate|hyclate|adipate|glucoheptonate)'
)

# Qualificatifs en fin de nom : « lévothyroxine sodique », « ... dihydraté ».
_QUALIFICATIFS = (
    r'(sodique|potassique|calcique|magnesique|monosodique|disodique|trisodique|'
    r'dipotassique|monopotassique|ferrique|ferreux|zincique|anhydre|monohydrate|'
    r'dihydrate|trihydrate|hexahydrate|pentahydrate|hydrate|micronise|micronisee|'
    r'synthetique|purifie|purifiee|lyophilise|'
    # Ajoutés le 12/08/2026 (P9-5). La liste ne connaissait que la forme
    # masculine : « doxycycline monohydratée » et « atorvastatine calcique
    # trihydratée » restaient non appariées alors que la molécule est
    # parfaitement identifiable. `base` désigne la forme non salifiée
    # (« ondansétron base », « kétamine base ») et ne distingue pas non plus
    # deux molécules.
    r'monohydratee|dihydratee|trihydratee|hemihydrate|hemihydratee|'
    r'sesquihydrate|sesquihydratee|pentahydratee|hexahydratee|anhydree|'
    r'base|micronises|lyophilisee)'
)

# Éléments et minéraux pour lesquels le sel EST le principe actif.
#
# La garde est indispensable et vérifiée : 8 de ces noms figurent dans
# `dci_lookup`. Sans elle, « chlorure de potassium » se réduirait à
# « potassium » et s'apparierait au potassium élémentaire — une entité
# différente, et un faux appariement pire qu'une absence d'appariement.
_MINERAUX = frozenset((
    'sodium', 'potassium', 'calcium', 'magnesium', 'zinc', 'fer', 'lithium',
    'aluminium', 'ammonium', 'argent', 'cuivre', 'manganese', 'selenium',
    'iode', 'phosphore', 'chrome', 'cobalt', 'molybdene', 'fluor', 'brome',
    'bismuth', 'strontium', 'baryum', 'or', 'platine',
))

# Sels postposés, à l'anglaise : « amikacin sulfate », « fingolimod
# hydrochloride ». La garde `_MINERAUX` reste indispensable — « sodium
# chloride » se réduirait sinon à « sodium ».
_SELS_ANGLAIS = (
    r'(hydrochloride|hydrobromide|mesilate|mesylate|besilate|besylate|'
    r'sulfate|sulphate|sodium|potassium|calcium|magnesium|acetate|maleate|'
    r'fumarate|succinate|tartrate|citrate|phosphate|nitrate|oxalate|lactate|'
    r'gluconate|bromide|chloride|iodide|tosilate|tosylate|xinafoate|'
    r'dipropionate|propionate|palmitate|stearate|pamoate|embonate|'
    r'diphosphate|dihydrochloride|disodium|dipotassium|hemifumarate|'
    r'hydrogen\s+tartrate|hydrogen\s+succinate|bitartrate|'
    r'dihydrate|monohydrate|trihydrate|hemihydrate|anhydrous|hydrate|base)'
)

_RE_SEL = re.compile(r'^\s*' + _SELS + r'\s+(?:de\s+|d\s+|du\s+|des\s+|de\s+l\s+)?')
_RE_QUALIF = re.compile(r'\s+' + _QUALIFICATIFS + r'\s*$')
_RE_SEL_ANGLAIS = re.compile(r'\s+' + _SELS_ANGLAIS + r'\s*$')
# « Eliglustat (tartrate) », « oritavancin (diphosphate) »
_RE_PARENTHESE = re.compile(r'\s*\([^)]*\)\s*$')
# Génitif français : marque qu'on n'a pas affaire à une forme anglaise.
_RE_GENITIF = re.compile(r'\s(?:de|du|des|d)\s')


def reduce_salt(text: str):
    """
    Réduit une forme salifiée à sa molécule.

    Rend None lorsque la réduction n'apporte rien ou serait abusive — nom
    inchangé, ou reste réduit à un simple élément chimique. Un appelant peut
    donc traiter None comme « pas de candidat supplémentaire », sans avoir à
    reproduire ces garde-fous.
    """
    base = normalize_dci(text)
    if not base:
        return None

    reduced = _RE_SEL.sub('', base)
    reduced = re.sub(r'\s+', ' ', reduced).strip()
    # Plusieurs qualificatifs peuvent s'enchaîner : « ... chlorure dihydraté ».
    for _ in range(3):
        stripped = _RE_QUALIF.sub('', reduced).strip()
        if stripped == reduced:
            break
        reduced = stripped

    # Formes anglaises, postposées : le français écrit « sulfate de X », la
    # source EMA écrit « X sulfate ». Nécessaire depuis l'import des
    # médicaments à procédure centralisée, dont les substances sont libellées
    # en DCI anglaise : 170 des 308 fiches restées non appariées s'y ramènent,
    # « dabigatran etexilate mesilate » en tête.
    #
    # La règle ne s'applique **qu'en l'absence de génitif français**. Sans
    # cette réserve, « folinate de calcium hydraté » perdait son contre-ion
    # postposé et rendait « folinate de » — une préposition orpheline, et un
    # appariement perdu.
    if not _RE_GENITIF.search(reduced):
        for _ in range(3):
            stripped = _RE_PARENTHESE.sub('', reduced).strip()
            stripped = _RE_SEL_ANGLAIS.sub('', stripped).strip()
            if stripped == reduced:
                break
            reduced = stripped

    if not reduced or reduced == base or reduced in _MINERAUX:
        return None
    return reduced
