# Sistema de Gerenciamento de Biblioteca

Projeto em Python 3.10 ou superior, utilizando apenas a biblioteca padrão.
Não é necessário instalar pacotes com pip.

## Execução

Extraia o ZIP, abra o terminal na pasta do projeto e execute:

```bash
python biblioteca.py
python -m unittest -v
```

A primeira execução cria `biblioteca.db` na mesma pasta do script. Para escolher
outro arquivo: `python biblioteca.py --banco meu_banco.db`. A demonstração acrescenta
dados em cada execução, sem apagar dados existentes. Os testes usam banco em memória.

## 1. Modelagem e conexão

`SCHEMA` cria autores, livros, membros e empréstimos. Um autor possui vários
livros; cada empréstimo referencia um livro e um membro. Uma instância de
`Biblioteca` abre a conexão e ativa `PRAGMA foreign_keys = ON` (necessário em cada
conexão SQLite). O gerenciador `with Biblioteca(...)` fecha a conexão ao terminar.

Chaves estrangeiras usam ON DELETE RESTRICT para preservar referências e
histórico. CHECK impede estoque negativo e estados de devolução incoerentes.
Emails são únicos, ignorando maiúsculas e minúsculas. Datas são armazenadas como
texto ISO AAAA-MM-DD. `data_devolucao` representa a devolução efetiva, não um prazo.

## 2. Funções de CRUD

- Create: `cadastrar_autor`, `cadastrar_livro`, `cadastrar_membro`.
- Read: `listar('autores')`, `listar('livros')`, `listar('membros')` ou
  `listar('emprestimos')`.
- Update: `atualizar('livros', id_livro, titulo='Novo título')`; também permite
  alterar campos autorizados de autores e membros.
- Delete: `excluir('membros', id_membro)`; também permite excluir autores e livros
  que não sejam referenciados.
- `registrar_emprestimo(livro_id, membro_id)` retorna o ID do empréstimo.
- `registrar_devolucao(emprestimo_id)` registra a devolução uma única vez.

Atualizar `quantidade_disponivel` significa ajustar o estoque físico disponível,
não a quantidade total incluindo exemplares emprestados. A devolução sempre soma
um exemplar. O histórico não pode ser alterado ou excluído pelo CRUD genérico.

O estoque e o empréstimo são escritos na mesma transação BEGIN IMMEDIATE,
com commit ou rollback. Isso evita retiradas concorrentes do último exemplar.
Um membro inexistente provoca rollback da redução de estoque. Cada thread deve
usar sua própria instância. Valores usam parâmetros `?`; identificadores dinâmicos
são limitados a listas de tabelas e colunas autorizadas.

`RegraNegocioError` informa problemas esperados. Erros SQLite são propagados
após rollback para o chamador tratar; o bloco principal trata IntegrityError e
outros sqlite3.Error com mensagem e código de saída 1.

## 3. Consultas avançadas

`listar_emprestimos_ativos()` executa JOIN entre empréstimos, membros e livros,
retornando uma lista de dicionários com ID, nome do membro, título, data e status.

## 4. Script de teste (Main)

O bloco `if __name__ == '__main__':` chama `demonstrar`: cadastra autor, livro e
membro; atualiza o nome; empresta; imprime o relatório; demonstra bloqueio por
estoque; devolve; demonstra bloqueio de devolução duplicada; cria e exclui um
autor temporário; e mostra o estoque final. O arquivo `test_biblioteca.py` verifica
o ciclo, o JOIN, rollback por FK inválida, CRUD, exclusões restritas e validações.

## Exemplo de uso como módulo

```python
from biblioteca import Biblioteca

with Biblioteca('meu_banco.db') as sistema:
    autor = sistema.cadastrar_autor('Clarice Lispector', 'Brasileira', '1920-12-10')
    livro = sistema.cadastrar_livro('A hora da estrela', 1977, 2, autor)
    membro = sistema.cadastrar_membro('João', 'joao@example.com')
    emprestimo = sistema.registrar_emprestimo(livro, membro)
    print(sistema.listar_emprestimos_ativos())
    sistema.registrar_devolucao(emprestimo)
```
