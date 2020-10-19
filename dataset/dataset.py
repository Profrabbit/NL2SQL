# TODO：创建读取SPARC和COSQL的dataset文件
import json
import pickle
import re
from torch.utils.data import Dataset
import torch


# 将数据改为全序列形式并添加<PAD>, 单个数据形式 [columns,u1,s1,u2,s2...u_m,s_m]
class DataLoad(Dataset):
    def __init__(self, max_length, data_ori):
        self.max_length = max_length
        self.structure = []
        self.data = []
        for item in data_ori:
            self.structure.append({'database': item['split_database'], 'pair': item['split_pair']})
            self.data.append(self.get_seq(item['split_database'], item['split_pair']))

    def get_seq(self, database, pair):
        _data = ['<pad>' for _ in range(
            self.max_length['db'] + self.max_length['turn'] * (self.max_length['utter'] + self.max_length['sql']))]
        _type = [0 for _ in range(
            self.max_length['db'] + self.max_length['turn'] * (self.max_length['utter'] + self.max_length['sql']))]
        for index in range(len(database['tokens'])):
            _data[index] = database['tokens'][index]
            _type[index] = database['types'][index]
        for turn in range(len(pair)):
            for index in range(len(pair[turn]['utterance']['tokens'])):
                _data[index + turn * (self.max_length['utter'] + self.max_length['sql']) + self.max_length['db']] \
                    = pair[turn]['utterance']['tokens'][index]
                _type[index + turn * (self.max_length['utter'] + self.max_length['sql']) + self.max_length['db']] \
                    = pair[turn]['utterance']['types'][index]
            sql_begin = self.max_length['db'] + self.max_length['utter']
            for index in range(len(pair[turn]['sql']['tokens'])):
                _data[index + turn * (self.max_length['utter'] + self.max_length['sql']) + sql_begin] \
                    = pair[turn]['sql']['tokens'][index]
                _type[index + turn * (self.max_length['utter'] + self.max_length['sql']) + sql_begin] \
                    = pair[turn]['sql']['types'][index]
        # return [_data, _type]
        return {'data': _data, 'type': torch.tensor(_type)}

    def __getitem__(self, index):
        assert index < len(self.data)
        return self.data[index]

    def __len__(self):
        return len(self.data)


# 构建数据集, 给定具体数据集，生成database，train，dev，各位置最大长度
class DataSetLoad():
    def __init__(self, opt, dataname='sparc_data', folder=''):
        self.root = folder + '/' + dataname
        if folder == '':
            self.root = dataname
        self.database_schema, self.column_names_surface_form, self.column_names_embedder_input = \
            self.read_database(self.root)
        self.train_ori = pickle.load(open(self.root + '/' + 'train.pkl', "rb+"))
        self.dev_ori = pickle.load(open(self.root + '/' + 'dev.pkl', "rb+"))
        self.max_length = self.getlegth()
        self.train = DataLoad(self.max_length, self.train_ori)
        self.dev = DataLoad(self.max_length, self.dev_ori)
        print(self.train.__getitem__(3))
        print("data already")

    # 读取数据库并将每个数据库内表与列添加seq表示法，按[表1,[表1内的列],表2,[表2内的列],...]排列，
    # 表的表示前附加<table>符号，列的表示前附加<column>符号
    def read_database(self, root):
        path = root + '/' + 'tables.json'
        with open(path, "r") as f:
            database_schema = json.load(f)

        database_schema_dict = {}
        column_names_surface_form = []
        column_names_embedder_input = []
        for table_schema in database_schema:
            db_id = table_schema['db_id']
            split_database = {'id': db_id, 'tokens': [], 'types': []}
            table_num = 0
            for column in table_schema['column_names']:
                if column[0] >= table_num:
                    split_table = re.split('[ _]', table_schema['table_names'][table_num])
                    split_database['tokens'] += ['<SEP>']
                    split_database['tokens'] += split_table
                    split_database['types'] += [0]
                    split_database['types'] += [1 for i in split_table]
                    table_num += 1
                split_column = re.split('[ _]', column[1])
                split_database['tokens'] += ['<SEP>']
                split_database['tokens'] += split_column
                split_database['types'] += [0]
                split_database['types'] += [2 for i in split_column]
            table_schema['split_database'] = split_database
            database_schema_dict[db_id] = table_schema
            column_names = table_schema['column_names']
            column_names_original = table_schema['column_names_original']
            table_names = table_schema['table_names']
            table_names_original = table_schema['table_names_original']

            for i, (table_id, column_name) in enumerate(column_names_original):
                column_name_surface_form = column_name
                column_names_surface_form.append(column_name_surface_form.lower())

            for table_name in table_names_original:
                column_names_surface_form.append(table_name.lower())

            for i, (table_id, column_name) in enumerate(column_names):
                column_name_embedder_input = column_name
                column_names_embedder_input.append(column_name_embedder_input.split())

            for table_name in table_names:
                column_names_embedder_input.append(table_name.split())

        database = database_schema
        database_schema = database_schema_dict

        return database_schema, column_names_surface_form, column_names_embedder_input

    # 根据数据表名和列名计算sql类型序列
    def get_sql_type(self, sql, database):
        _type = []
        stat = 0
        word = ''
        database_ori = self.database_schema[database['id']]
        for item in sql:
            if item not in database['tokens']:
                if stat:
                    if word in database_ori['table_names']:
                        _type += [1 for _ in range(stat)]
                    else:
                        _type += [2 for _ in range(stat)]
                word = ''
                stat = 0
                _type.append(3)
            else:
                stat += 1
                word += item
        if stat:
            if word in database_ori:
                _type += [1 for _ in range(stat)]
            else:
                _type += [2 for _ in range(stat)]
        return _type

    # 获取各类型最大长度，并生成分割好的序列化数据
    def getlegth(self):
        max_legth = {}
        max_legth['db'] = 0
        max_legth['turn'] = 0
        max_legth['utter'] = 0
        max_legth['sql'] = 0
        # 先找train最大长度
        for item in self.train_ori:
            split_interaction = []
            item['split_database'] = self.database_schema[item['database_id']]['split_database']
            turn = len(item['interaction'])
            max_legth['turn'] = max(max_legth['turn'], turn + 1)
            for pair in item['interaction']:
                utterance = re.split('[ _]', pair['utterance'])
                sql = list(pair['sql'][0][0])
                max_legth['sql'] = max(max_legth['sql'], len(sql) + 1)
                max_legth['utter'] = max(max_legth['utter'], len(utterance) + 1)
                split_pair = {'utterance': {'tokens': ['<SEP>'] + utterance, 'types': [0] + [0 for _ in utterance]},
                              'sql': {'tokens': ['<SEP>'] + sql,
                                      'types': [0] + self.get_sql_type(sql, item['split_database'])}}
                split_interaction.append(split_pair)
            utterance = re.split('[ _]', item['final']['utterance'])
            sql = re.split('[ _]', item['final']['sql'])
            sql = [token.lower() for token in sql]
            max_legth['sql'] = max(max_legth['sql'], len(sql) + 1)
            max_legth['utter'] = max(max_legth['utter'], len(utterance) + 1)
            split_pair = {'utterance': {'tokens': ['<SEP>'] + utterance, 'types': [0] + [0 for _ in utterance]},
                          'sql': {'tokens': ['<SEP>'] + sql,
                                  'types': [0] + self.get_sql_type(sql, item['split_database'])}}
            split_interaction.append(split_pair)
            item['split_pair'] = split_interaction
            max_legth['db'] = max(max_legth['db'], len(item['split_database']['tokens']))

        # 再找dev最大长度
        for item in self.dev_ori:
            split_interaction = []
            item['split_database'] = self.database_schema[item['database_id']]['split_database']
            turn = len(item['interaction'])
            max_legth['turn'] = max(max_legth['turn'], turn + 1)
            for pair in item['interaction']:
                utterance = re.split('[ _]', pair['utterance'])
                sql = list(pair['sql'][0][0])
                max_legth['sql'] = max(max_legth['sql'], len(sql))
                max_legth['utter'] = max(max_legth['utter'], len(utterance))
                split_pair = {'utterance': {'tokens': ['<SEP>'] + utterance, 'types': [0] + [0 for _ in utterance]},
                              'sql': {'tokens': ['<SEP>'] + sql,
                                      'types': [0] + self.get_sql_type(sql, item['split_database'])}}
                split_interaction.append(split_pair)
            utterance = re.split('[ _]', item['final']['utterance'])
            sql = re.split('[ _]', item['final']['sql'])
            sql = [token.lower() for token in sql]
            max_legth['sql'] = max(max_legth['sql'], len(sql))
            max_legth['utter'] = max(max_legth['utter'], len(utterance))
            split_pair = {'utterance': {'tokens': ['<SEP>'] + utterance, 'types': [0] + [0 for _ in utterance]},
                          'sql': {'tokens': ['<SEP>'] + sql,
                                  'types': [0] + self.get_sql_type(sql, item['split_database'])}}
            split_interaction.append(split_pair)
            item['split_pair'] = split_interaction
            max_legth['db'] = max(max_legth['db'], len(item['split_database']['tokens']))

        return max_legth


if __name__ == '__main__':
    from torch.utils.data import DataLoader

    dataset = DataSetLoad(1)
    train_dataset = dataset.train
    dev_dataset = dataset.dev
    train_data_loader = DataLoader(train_dataset, batch_size=3)
    for batch in train_data_loader:
        print(batch)
'''


sample:
{
    "id": "",
    "scenario": "",
    "database_id": "hospital_1",
    "interaction_id": 0,
    "final": {
        "utterance": "Find the department with the most employees.",
        "sql": "SELECT name FROM department GROUP BY departmentID ORDER BY count(departmentID) DESC LIMIT 1;"
    },
    "interaction": [
        {
            "utterance": "What is the number of employees in each department ?",
            "sql": "select count ( departmentid ) from department group by departmentid"
        },
        {
            "utterance": "Which department has the most employees ? Give me the department name .",
            "sql": "select name from department group by departmentid order by count ( departmentid ) desc limit value"
        }
    ]
}

__getitem__:

{
'Table':"<CLS> physician <SEP> department <SEP> affiliated with <SEP> procedures ....<SEP> undergoes <SEP> <PAD>...<PAD>“ <<<<<<<  小于args.tl的padding至args.tl，大于args.tl的样本需要进行截取

'Column':"<SEP> * <SEP> employee id <SEP> name <SEP> position <SEP> ... <SEP> assisting nurse <SEP> <PAD>...<PAD>" <<<<<<<  小于args.cl的padding至args.cl，大于args.cl的样本需要进行截取


‘Utterance’:
['<SEP> What is the number of employees in each department ? <SEP> <PAD>...<PAD>','<SEP> Which department has the most employees ? Give me the department name . <SEP> <PAD>...<PAD>']
<<<<<<<  utterance中每个句子的长度，如果小于args.ul padding到args.ul，如果大于args.ul那么就扔到最后的几个单词
<<<<<<<  utterance的轮数我们不处理，原来有多少轮，这个list中就放多少轮

'SQL':
['<SEP> select count ( departmentid ) from department group by departmentid <EOS> <PAD>...<PAD> ',
'<SEP> select name from department group by departmentid order by count ( departmentid ) desc limit value <EOS> <PAD>...<PAD> ']
<<<<<<<  sql中每个句子的长度，如果小于args.sl就padding到args.sl，如果大于args.sl那么就扔到最后的几个单词
<<<<<<<  sql的轮数我们不处理，原来有多少轮，这个list中就放多少轮

'input': [
concat
] 
<<<<<<<  将Table，Column，utterance1，sql1拼接起来 长度等于 tl+cl+ul+sl 的， 


'Modality':
[[1]* tl +[2]*cl + [4]*len(utterance1) + sql1的组合}
,}
] <<<<<<<<<1表示table 2表示column 3表示utterance 4表示sql 0无

'position':
不需要，在模型forward中即可定义
’temporal‘：
不需要，在模型forward中即可定义

’dbcomponent‘:
db 0 无  1 table1 2 table2 3 table3 先不考虑sql
} 


:param position: -
:param modality: 0 无， 1 table 2 column 3 keyword 4 自然语言
:param temporal: 0 db， 第一轮：1 ，，，
:param db 0 无  1 table1 2 table2 3 table3 先不考虑sql


'''
