"""Gerenciamento de biblioteca com SQLite. Requer Python 3.10+."""

import argparse
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path


class RegraNegocioError(ValueError):
    """Operação incompatível com as regras da biblioteca."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS autores (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL CHECK (length(trim(nome)) > 0),
    nacionalidade TEXT NOT NULL,
    data_nascimento TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS livros (
    id INTEGER PRIMARY KEY,
    titulo TEXT NOT NULL CHECK (length(trim(titulo)) > 0),
    ano_publicacao INTEGER NOT NULL CHECK (ano_publicacao > 0),
    quantidade_disponivel INTEGER NOT NULL
        CHECK (quantidade_disponivel >= 0),
    autor_id INTEGER NOT NULL REFERENCES autores(id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS membros (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL CHECK (length(trim(nome)) > 0),
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    data_cadastro TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS emprestimos (
    id INTEGER PRIMARY KEY,
    livro_id INTEGER NOT NULL REFERENCES livros(id) ON DELETE RESTRICT,
    membro_id INTEGER NOT NULL REFERENCES membros(id) ON DELETE RESTRICT,
    data_emprestimo TEXT NOT NULL,
    data_devolucao TEXT,
    status TEXT NOT NULL DEFAULT 'ativo'
        CHECK (status IN ('ativo', 'devolvido')),
    CHECK ((status = 'ativo' AND data_devolucao IS NULL)
        OR (status = 'devolvido' AND data_devolucao IS NOT NULL
            AND data_devolucao >= data_emprestimo))
);
CREATE INDEX IF NOT EXISTS idx_livros_autor ON livros(autor_id);
CREATE INDEX IF NOT EXISTS idx_emprestimos_livro ON emprestimos(livro_id);
CREATE INDEX IF NOT EXISTS idx_emprestimos_membro ON emprestimos(membro_id);
CREATE INDEX IF NOT EXISTS idx_emprestimos_status ON emprestimos(status);
"""


class Biblioteca:
    """Uma conexão por instância; use uma instância por thread.

    Escritas usam transações IMMEDIATE: estoque e empréstimo são alterados
    juntos, inclusive quando existem conexões concorrentes.
    """

    CAMPOS = {
        'autores': {'nome', 'nacionalidade', 'data_nascimento'},
        'livros': {'titulo', 'ano_publicacao', 'quantidade_disponivel',
                   'autor_id'},
        'membros': {'nome', 'email'},
    }

    def __init__(self, caminho='biblioteca.db'):
        self.conexao = sqlite3.connect(caminho, isolation_level=None, timeout=10)
        self.conexao.row_factory = sqlite3.Row
        try:
            self.conexao.execute('PRAGMA foreign_keys = ON')
            self.conexao.executescript(SCHEMA)
        except sqlite3.Error:
            self.conexao.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.conexao.close()

    @contextmanager
    def transacao(self):
        """Confirma toda a operação ou desfaz suas alterações em caso de erro."""
        self.conexao.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.conexao.commit()
        except Exception:
            self.conexao.rollback()
            raise

    @staticmethod
    def validar_campos(campos):
        """Valida tipos e datas antes de enviar valores parametrizados ao SQL."""
        for campo, valor in campos.items():
            if campo in {'ano_publicacao', 'quantidade_disponivel', 'autor_id'}:
                minimo = 0 if campo == 'quantidade_disponivel' else 1
                if type(valor) is not int or valor < minimo:
                    raise RegraNegocioError(f'Valor inválido para {campo}.')
            else:
                if not isinstance(valor, str) or not valor.strip():
                    raise RegraNegocioError(f'{campo} não pode ficar vazio.')
            if campo == 'data_nascimento':
                try:
                    nascimento = date.fromisoformat(valor)
                except ValueError as erro:
                    raise RegraNegocioError('Use uma data AAAA-MM-DD.') from erro
                if nascimento > date.today():
                    raise RegraNegocioError('Nascimento não pode ser futuro.')
            if campo == 'email' and ('@' not in valor or ' ' in valor):
                raise RegraNegocioError('Email inválido.')

    def _inserir(self, tabela, campos):
        """Insere apenas em tabelas e colunas autorizadas internamente."""
        self._validar_tabela(tabela)
        permitidos = self.CAMPOS[tabela] | {'data_cadastro'}
        if not campos or not set(campos) <= permitidos:
            raise RegraNegocioError('Campos não permitidos.')
        self.validar_campos(campos)
        colunas = ', '.join(campos)
        parametros = ', '.join('?' for _ in campos)
        with self.transacao():
            cursor = self.conexao.execute(
                f'INSERT INTO {tabela} ({colunas}) VALUES ({parametros})',
                tuple(campos.values()),
            )
        return cursor.lastrowid

    def cadastrar_autor(self, nome, nacionalidade, data_nascimento):
        """Cadastra autor com nascimento no formato AAAA-MM-DD."""
        return self._inserir('autores', dict(
            nome=nome, nacionalidade=nacionalidade,
            data_nascimento=data_nascimento,
        ))

    def cadastrar_livro(self, titulo, ano_publicacao, quantidade, autor_id):
        """Cadastra livro associado a um autor existente."""
        return self._inserir('livros', dict(
            titulo=titulo, ano_publicacao=ano_publicacao,
            quantidade_disponivel=quantidade, autor_id=autor_id,
        ))

    def cadastrar_membro(self, nome, email):
        """Cadastra membro com email único e data de cadastro automática."""
        return self._inserir('membros', dict(
            nome=nome, email=email, data_cadastro=date.today().isoformat(),
        ))

    def listar(self, tabela):
        """Consulta cadastros ou histórico de empréstimos, ordenados por ID."""
        self._validar_tabela(tabela, incluir_emprestimos=True)
        return [dict(linha) for linha in self.conexao.execute(
            f'SELECT * FROM {tabela} ORDER BY id'
        )]

    def _validar_tabela(self, tabela, incluir_emprestimos=False):
        permitidas = set(self.CAMPOS)
        if incluir_emprestimos:
            permitidas.add('emprestimos')
        if tabela not in permitidas:
            raise RegraNegocioError('Tabela não permitida.')

    def atualizar(self, tabela, registro_id, **campos):
        """Atualiza cadastros; empréstimos só mudam pelas operações próprias."""
        self._validar_tabela(tabela)
        if not campos or not set(campos) <= self.CAMPOS[tabela]:
            raise RegraNegocioError('Campos não permitidos para atualização.')
        self.validar_campos(campos)
        atribuicoes = ', '.join(f'{campo} = ?' for campo in campos)
        with self.transacao():
            cursor = self.conexao.execute(
                f'UPDATE {tabela} SET {atribuicoes} WHERE id = ?',
                (*campos.values(), registro_id),
            )
            if cursor.rowcount != 1:
                raise RegraNegocioError('Registro não encontrado.')

    def excluir(self, tabela, registro_id):
        """Exclui cadastro sem referências; preserva histórico de empréstimos."""
        self._validar_tabela(tabela)
        with self.transacao():
            cursor = self.conexao.execute(
                f'DELETE FROM {tabela} WHERE id = ?', (registro_id,)
            )
            if cursor.rowcount != 1:
                raise RegraNegocioError('Registro não encontrado.')

    def registrar_emprestimo(self, livro_id, membro_id):
        """Retira um exemplar e cria empréstimo em uma única transação."""
        with self.transacao():
            livro = self.conexao.execute(
                'SELECT id FROM livros WHERE id = ?', (livro_id,)
            ).fetchone()
            if livro is None:
                raise RegraNegocioError('Livro não encontrado.')
            cursor = self.conexao.execute(
                'UPDATE livros SET quantidade_disponivel = '
                'quantidade_disponivel - 1 '
                'WHERE id = ? AND quantidade_disponivel > 0', (livro_id,)
            )
            if cursor.rowcount != 1:
                raise RegraNegocioError('Não há exemplares disponíveis.')
            # Uma FK inválida provoca rollback também da redução do estoque.
            cursor = self.conexao.execute(
                'INSERT INTO emprestimos '
                '(livro_id, membro_id, data_emprestimo) VALUES (?, ?, ?)',
                (livro_id, membro_id, date.today().isoformat()),
            )
        return cursor.lastrowid

    def registrar_devolucao(self, emprestimo_id):
        """Devolve um exemplar; impede devolução duplicada e estoque indevido."""
        with self.transacao():
            emprestimo = self.conexao.execute(
                'SELECT livro_id, status FROM emprestimos WHERE id = ?',
                (emprestimo_id,),
            ).fetchone()
            if emprestimo is None:
                raise RegraNegocioError('Empréstimo não encontrado.')
            if emprestimo['status'] != 'ativo':
                raise RegraNegocioError('Este empréstimo já foi devolvido.')
            self.conexao.execute(
                "UPDATE emprestimos SET status = 'devolvido', "
                'data_devolucao = ? WHERE id = ?',
                (date.today().isoformat(), emprestimo_id),
            )
            self.conexao.execute(
                'UPDATE livros SET quantidade_disponivel = '
                'quantidade_disponivel + 1 WHERE id = ?',
                (emprestimo['livro_id'],),
            )

    def listar_emprestimos_ativos(self):
        """JOIN entre empréstimos, membros e livros para relatório legível."""
        consulta = """
            SELECT e.id, m.nome AS membro, l.titulo AS livro,
                   e.data_emprestimo, e.status
            FROM emprestimos AS e
            JOIN membros AS m ON m.id = e.membro_id
            JOIN livros AS l ON l.id = e.livro_id
            WHERE e.status = 'ativo'
            ORDER BY e.data_emprestimo, e.id
        """
        return [dict(linha) for linha in self.conexao.execute(consulta)]


def demonstrar(caminho):
    """Acrescenta dados de demonstração sem apagar registros existentes."""
    with Biblioteca(caminho) as biblioteca:
        autor = biblioteca.cadastrar_autor(
            'Machado de Assis', 'Brasileira', '1839-06-21'
        )
        livro = biblioteca.cadastrar_livro('Dom Casmurro', 1899, 1, autor)
        # O ID do autor torna o email exclusivo em cada execução da demonstração.
        membro = biblioteca.cadastrar_membro(
            'Ana Souza', f'ana.demo.{autor}@example.com'
        )
        biblioteca.atualizar('membros', membro, nome='Ana Souza Lima')
        emprestimo = biblioteca.registrar_emprestimo(livro, membro)
        print('Empréstimos ativos:', biblioteca.listar_emprestimos_ativos())
        try:
            biblioteca.registrar_emprestimo(livro, membro)
        except RegraNegocioError as erro:
            print('Bloqueio esperado:', erro)
        biblioteca.registrar_devolucao(emprestimo)
        try:
            biblioteca.registrar_devolucao(emprestimo)
        except RegraNegocioError as erro:
            print('Bloqueio esperado:', erro)
        temporario = biblioteca.cadastrar_autor(
            'Autor temporário', 'BR', '1990-01-01'
        )
        biblioteca.excluir('autores', temporario)
        print('Livros após a devolução:', biblioteca.listar('livros'))
        print('Ativos após a devolução:', biblioteca.listar_emprestimos_ativos())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--banco', default=str(Path(__file__).with_name('biblioteca.db')),
        help='Caminho do banco SQLite (criado automaticamente).',
    )
    argumentos = parser.parse_args()
    try:
        demonstrar(argumentos.banco)
    except sqlite3.IntegrityError as erro:
        parser.exit(1, f'Erro de integridade (FK, unicidade ou restrição): {erro}\n')
    except sqlite3.Error as erro:
        parser.exit(1, f'Erro de banco de dados: {erro}\n')
    except (RegraNegocioError, OSError) as erro:
        parser.exit(1, f'Erro: {erro}\n')
