"""Testes de integridade e das regras de estoque, sem dependências externas."""

import sqlite3
import unittest

from biblioteca import Biblioteca, RegraNegocioError


class TestBiblioteca(unittest.TestCase):
    def setUp(self):
        self.b = Biblioteca(':memory:')
        self.addCleanup(self.b.conexao.close)
        self.autor = self.b.cadastrar_autor('Autor', 'BR', '1980-01-01')
        self.livro = self.b.cadastrar_livro('Livro', 2020, 1, self.autor)
        self.membro = self.b.cadastrar_membro('Ana', 'ana@example.com')

    def estoque(self):
        return self.b.listar('livros')[0]['quantidade_disponivel']

    def test_ciclo_e_relatorio(self):
        eid = self.b.registrar_emprestimo(self.livro, self.membro)
        self.assertEqual(self.estoque(), 0)
        ativo = self.b.listar_emprestimos_ativos()[0]
        self.assertEqual((ativo['membro'], ativo['livro']), ('Ana', 'Livro'))
        with self.assertRaises(RegraNegocioError):
            self.b.registrar_emprestimo(self.livro, self.membro)
        self.b.registrar_devolucao(eid)
        self.assertEqual(self.estoque(), 1)
        self.assertEqual(self.b.listar_emprestimos_ativos(), [])
        with self.assertRaises(RegraNegocioError):
            self.b.registrar_devolucao(eid)
        self.assertEqual(self.estoque(), 1)

    def test_fk_invalida_desfaz_estoque(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.b.registrar_emprestimo(self.livro, 999)
        self.assertEqual(self.estoque(), 1)
        self.assertEqual(self.b.listar('emprestimos'), [])

    def test_crud_e_exclusao_restrita(self):
        self.b.atualizar('livros', self.livro, titulo='Novo título')
        self.assertEqual(self.b.listar('livros')[0]['titulo'], 'Novo título')
        with self.assertRaises(sqlite3.IntegrityError):
            self.b.excluir('autores', self.autor)
        eid = self.b.registrar_emprestimo(self.livro, self.membro)
        self.b.registrar_devolucao(eid)
        with self.assertRaises(sqlite3.IntegrityError):
            self.b.excluir('livros', self.livro)
        outro = self.b.cadastrar_membro('Bia', 'bia@example.com')
        self.b.excluir('membros', outro)
        self.assertEqual(len(self.b.listar('membros')), 1)

    def test_validacao_e_email_unico(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.b.cadastrar_membro('Outra', 'ANA@example.com')
        with self.assertRaises(RegraNegocioError):
            self.b.cadastrar_livro('Livro', 2020, -1, self.autor)
        with self.assertRaises(RegraNegocioError):
            self.b.registrar_devolucao(999)
        with self.assertRaises(RegraNegocioError):
            self.b.listar('livros; DROP TABLE autores')


if __name__ == '__main__':
    unittest.main()
