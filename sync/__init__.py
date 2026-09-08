"""
Socle de synchronisation MedicSearch.

Deux détecteurs de changement (réconciliation par dumps officiels, sonde de
révision des notices) alimentent une file de travaux persistée dans MongoDB.

Aucun module de ce paquet ne consomme la file : la publication vers
`medicines` relève de la phase P3.
"""

__all__ = ['config', 'jobs', 'locks', 'ansm_dumps', 'reconciliation', 'probe']
