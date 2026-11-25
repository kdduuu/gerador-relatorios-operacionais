import unittest
from unittest.mock import Mock

from src.ler_pdf import extrair_distribuicao_horaria


def palavra(x, y, texto):
    return (x, y, x + 20, y + 8, texto, 0, 0, 0)


class TestDistribuicaoHoraria(unittest.TestCase):
    def pagina_ficticia(self, conflito=False):
        # A cada hora, o gráfico avança 19 pontos no eixo vertical.
        palavras = [palavra(69, 386 - (h - 6) * 19, f"{h:02d}:00")
                    for h in range(6, 24, 2)]
        palavras += [palavra(104, 386 - (h - 6) * 19, "3" if h == 10 else "0")
                     for h in range(6, 24)]
        palavras.append(palavra(104, 386 - (10 - 6) * 19, "4" if conflito else "3"))
        pagina = Mock()
        pagina.get_text.return_value = palavras
        return pagina

    def test_valores_repetidos_nao_duplicam(self):
        horarios = extrair_distribuicao_horaria(self.pagina_ficticia())
        self.assertEqual(len(horarios), 18)
        self.assertEqual(sum(v["quantidade"] for v in horarios), 3)
        self.assertEqual(horarios[4], {"hora": "10:00", "quantidade": 3})

    def test_duplicacoes_conflitantes_sao_rejeitadas(self):
        with self.assertRaisesRegex(ValueError, "conflitantes"):
            extrair_distribuicao_horaria(self.pagina_ficticia(conflito=True))


if __name__ == "__main__":
    unittest.main()