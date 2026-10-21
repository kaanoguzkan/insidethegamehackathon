// Strings of the first-run welcome and the tools menu.
import type { Lang } from './lib/types'

type Dict = Record<string, string>

const en: Dict = {
  'welcome.title': 'A match, explained as it happens',
  'welcome.body': 'The data is synthetic. Code computes the numbers; AI agents choose the moments and write the story for you, and a verifier checks every claim against the data.',
  'welcome.li1': 'Press Play, or pick a moment on the right to jump to it.',
  'welcome.li2': 'Change the viewer (analyst or fan, language, club, player): the same match is told differently.',
  'welcome.li3': 'Or play it live: the match is analysed while it is played.',
  'welcome.play': 'Play the match',
  'welcome.live': 'Play live',
  'welcome.skip': 'Skip',
  'tools.menu': 'Tools',
  'tools.title': 'Tools for judges and developers',
  'tools.ai': 'Live AI',
  'tools.aiOn': 'on',
  'tools.aiOff': 'off',
}
const es: Dict = {
  'welcome.title': 'Un partido, explicado mientras ocurre',
  'welcome.body': 'Los datos son sintéticos. El código calcula las cifras; los agentes de IA eligen los momentos y escriben la historia para ti, y un verificador comprueba cada afirmación con los datos.',
  'welcome.li1': 'Pulsa Reproducir, o elige un momento a la derecha para saltar a él.',
  'welcome.li2': 'Cambia el espectador (analista o aficionado, idioma, club, jugador): el mismo partido se cuenta distinto.',
  'welcome.li3': 'O juégalo en vivo: el partido se analiza mientras se juega.',
  'welcome.play': 'Reproducir el partido',
  'welcome.live': 'Jugar en vivo',
  'welcome.skip': 'Omitir',
  'tools.menu': 'Herramientas',
  'tools.title': 'Herramientas para jueces y desarrolladores',
  'tools.ai': 'IA en directo',
  'tools.aiOn': 'activada',
  'tools.aiOff': 'desactivada',
}
const tr: Dict = {
  'welcome.title': 'Olurken anlatılan bir maç',
  'welcome.body': 'Veriler sentetiktir. Kod sayıları hesaplar; yapay zekâ ajanları anları seçip hikâyeyi sizin için yazar, bir doğrulayıcı her iddiayı verilerle kontrol eder.',
  'welcome.li1': 'Oynat’a basın ya da sağdan bir an seçip oraya atlayın.',
  'welcome.li2': 'İzleyiciyi değiştirin (analist veya taraftar, dil, kulüp, oyuncu): aynı maç farklı anlatılır.',
  'welcome.li3': 'Ya da canlı oynatın: maç oynanırken analiz edilir.',
  'welcome.play': 'Maçı oynat',
  'welcome.live': 'Canlı oynat',
  'welcome.skip': 'Geç',
  'tools.menu': 'Araçlar',
  'tools.title': 'Jüri ve geliştiriciler için araçlar',
  'tools.ai': 'Canlı YZ',
  'tools.aiOn': 'açık',
  'tools.aiOff': 'kapalı',
}
export const UX: Record<Lang, Dict> = { en, es, tr }
