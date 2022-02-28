# -*- coding: utf-8 -*-
import datetime
import itertools
import os
import shutil
from tqdm import tqdm
import chardet
import matplotlib as mpl
import matplotlib.pyplot as plt
from mpl_toolkits import mplot3d
import numpy as np
import pandas as pd
from scipy import stats, integrate
import seaborn as sns
from io import StringIO

mpl.rcParams['font.sans-serif'] = ['SimHei']
mpl.rcParams['axes.unicode_minus'] = False

pd.set_option('display.float_format', lambda x: '%.7f' % x)

# ----------------------------------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------------------------------

field = np.array([
    '风场1',
    '风场2'
])
field_len = field.shape[0]

machine = np.array([
    [f'x{i}' for i in range(26, 50 + 1)],
    [f'x{i}' for i in range(25, 49 + 1)]
])
machine_len = machine[0].shape[0]

season = np.array(['春', '夏', '秋', '冬'])
season_len = season.shape[0]

period = np.array([f'{s}_{str(i).zfill(2)}' for s in season for i in range(1, 20 + 1)])
period_len = period.shape[0]

# ----------------------------------------------------------------------------------------------------

# 各风场对应的年份
years = {
    field[0]: [2018, 2019],
    field[1]: [2017, 2018]
}

# 完整的时间序列
time_series = {field[f]: pd.DataFrame(data={'time': pd.date_range(datetime.datetime(years[field[f]][0], 1, 1, 0, 0, 0),
                                                                  datetime.datetime(years[field[f]][1], 12, 31, 23, 59,
                                                                                    30), freq='30S')}, dtype=str) for f
               in range(field_len)}


# ----------------------------------------------------------------------------------------------------
# Data Manager
# ----------------------------------------------------------------------------------------------------

def read_csv(path):
    if os.path.exists(path.encode('utf-8')):
        f = open(path.encode('utf-8'), encoding="utf-8")
        return pd.read_csv(f)
    else:
        None


class Data_Manager():
    def __init__(self):
        super().__init__()
        self.root = os.path.join('data','训练集')

        if self._check_file:  # 看是不是已经merge训练集
            print('正在合并同一台风机的数据并修复缺失的时间段')
            self._merge_data

        # itertools.product，对应有序的重复抽样过程
        self.sample = pd.DataFrame(
            data=np.array([
                [*x0, x1, x2, x3, x4] for x0, x1, x2, x3, x4 in
                itertools.product(
                    np.vstack([list(itertools.product([field[f]], machine[f])) for f in range(field_len)]).tolist(),
                    # '风场', '风机'
                    period,  # '时段'
                    np.arange(1, 20 + 1) * 30,  # '时刻'
                    [None],  # '风速'
                    [None]  # '风向'
                )
            ]),
            columns=['风场', '风机', '时段', '时刻', '风速', '风向']
        )
        print(self.sample)
        self.test_pred_df = self.sample.copy()  # 这里应该是最后预测生成的结果，内容是最后要提交的文件，但是风速和风向没有


    def load_train_data(self):

        """
                       [风场, 时段, 风机, 时刻, 特征]
        self.X_ : shape: (2, 17507, 25, 120, 2)    机舱数据，用作训练；特征 ['变频器电网侧有功功率', '外界温度'] 时段单位是1小时
        self.X0 : shape: (2, 17507, 25, 120, 2)    机舱数据，用作训练；特征 ['风速', '风向']
        self.Y0 : shape: (2, 17507, 25,  20, 2)    机舱数据，用作训练；特征 ['风速', '风向']

                       [风场, 时段]
        self.S  : shape: (2, 17507)                季节数据，用作训练

                       [风场, 时段, 时刻, 特征]
        self.W  : shape: (2, 17507, 14, 2)         气象数据，用作训练；特征 ['风速', '风向']

                            [风场, 时段, 风机, 特征]
        self.weather : shape: (2, 17520, 26, 2)    机舱数据+气象数据；特征 ['风速', '风向']  时段单位是1小时
        """

        print(f'正在加载 {self.root}')

        '''
        部分数字说明
            730 * 24 - 13 : 730 天 <- 365 * 2; 24 小时; 13 个预留时间（小时），最前面预留11个小时，最后面预留2个小时
            17507 <- 730 * 24 - 13
            17520 <- 730 * 24
            120 : (1小时) 120个 (30秒)
            14 : 13个小时，14个时间点
        '''
        '''
        full(shape, fill_value, dtype=None, order='C')
        shape：int 或者 int元组
        fill_value：填充到数组中的值
        '''
        self.X_ = np.full((field_len, machine_len, 730 * 24 - 13, 120, 2), np.nan,  # 减去开始13个小时
                          dtype=np.float32)  # shape: (2, 25, 17507, 120, 2)
        self.X0 = np.full((field_len, machine_len, 730 * 24 - 13, 120, 2), np.nan,
                          dtype=np.float32)  # shape: (2, 25, 17507, 120, 2)
        self.Y0 = np.full((field_len, machine_len, 730 * 24 - 13, 20, 2), np.nan,
                          dtype=np.float32)  # shape: (2, 25, 17507, 20, 2)
        self.S = np.full((field_len, 730 * 24 - 13), np.nan, dtype=str)  # shape: (2, 17507)
        self.W = np.full((field_len, 730 * 24 - 13, 14, 2), np.nan, dtype=np.float32)  # shape: (2, 17507, 14, 2)

        # columns = ['time', 'wind_spd', 'wind_dir']
        weather = {field[f]: read_csv(os.path.join(self.root, field[f], 'weather.csv')) for f in range(field_len)}
        print("--------------------------------")
        print(weather)
        self.weather = {
            'time': {field[f]: weather[field[f]]['time'] for f in range(field_len)},
            'data': np.zeros((2, 26, 17520, 2), dtype=np.float32)
        }

        for f in range(field_len):

            self.weather['data'][f, 25, ...] = weather[field[f]][['wind_spd', 'wind_dir']].values

            for m in range(machine_len):  #所有风机全部加载
                datas = read_csv(os.path.join(self.root, field[f], machine[f][m]) + '.csv')
                print(f'{os.path.join(self.root, field[f], machine[f][m])}.csv')
                # 11*120+1 : 正数第11个小时30秒开始
                # -2*120+1 : 倒数第2个小时结束（不包含最后2小时）
                # 每一个时段由每小时的第30秒开始第3600秒结束，共120个时刻
                self.X_[f, m, ...] = datas[11 * 120 + 1:-2 * 120 + 1][['变频器电网侧有功功率', '外界温度']].values.reshape(
                    730 * 24 - 13, 120, 2)
                self.X0[f, m, ...] = datas[11 * 120 + 1:-2 * 120 + 1][['风速', '风向']].values.reshape(730 * 24 - 13, 120,
                                                                                                   2)

                # 12*120+1 : 正数第12个小时30秒开始
                # -1*120+1 : 倒数第1个小时结束（不包含最后1小时）
                # 每一个时段由每小时的第30秒开始第600秒结束，共20个时刻
                self.Y0[f, m, ...] = datas[12 * 120 + 1:-1 * 120 + 1][['风速', '风向']].values.reshape(730 * 24 - 13, 120,
                                                                                                   2)[:, :20, :]

                self.weather['data'][f, m, ...] = datas[::120][['风速', '风向']].values

            self.S[f] = time_series[field[f]]['time'].str.split(' ').str.get(0).str.split('-').map(
                lambda x: season[np.ceil(int(x[1]) / 3).astype(int) - 1])[11 * 120:-2 * 120].values.reshape(
                730 * 24 - 13, 120)[:, 0]

            for i in range(730 * 24 - 13):
                self.W[f, i, ...] = weather[field[f]][i:i + 14][['wind_spd', 'wind_dir']].values

        self.X_ = np.moveaxis(self.X_, 1, 2)  # 将数组的轴移到新位置。其他轴保持其原始顺序。
        self.X0 = np.moveaxis(self.X0, 1, 2)

        self.Y0 = np.moveaxis(self.Y0, 1, 2)

        self.weather['data'] = np.moveaxis(self.weather['data'], 1, 2)

        # ---------- update ----------
        # self.n_indexes = (np.isnan(self.X0.reshape(2 * 17507, 25 * 120 * 2)).astype(np.float32).sum(-1) == 0).reshape(2, 17507) * (np.isnan(self.Y0.reshape(2 * 17507, 25 * 20 * 2)).astype(np.float32).sum(-1) == 0).reshape(2, 17507)
        # ---------- update ----------

    def load_test_data(self, test_findals=False):

        """
                            [风场, 时段, 风机, 时刻, 特征]
        self.test_X_ : shape: (2, 80, 25, 120, 2)       机舱数据，用作测试；特征 ['变频器电网侧有功功率', '外界温度']
        self.test_X0 : shape: (2, 80, 25, 120, 2)       机舱数据，用作测试；特征 ['风速', '风向']

                            [风场, 时段, 时刻, 特征]
        self.test_W  : shape: (2, 80, 14, 2)            气象数据，用作测试；特征 ['风速', '风向']
        """

        root = './data/测试集_决赛' if test_findals else './data/测试集_初赛'

        print(f'正在加载 {root}')

        self.test_X_ = np.full((field_len, machine_len, period_len, 120, 2), np.nan,
                               dtype=np.float32)  # shape: (2, 25, 80, 120, 2)
        self.test_X0 = np.full((field_len, machine_len, period_len, 120, 2), np.nan,
                               dtype=np.float32)  # shape: (2, 25, 80, 120, 2)
        self.test_W = np.full((field_len, period_len, 14, 2), np.nan, dtype=np.float32)  # shape: (2, 80, 14, 2)

        # columns = ['时段', '时刻', '风速', '风向']
        weather = {field[f]: read_csv(os.path.join(root, field[f], 'weather.csv')) for f in range(field_len)}

        for f in range(field_len):
            for m in tqdm(range(machine_len)):
                for p in range(period_len):
                    datas = read_csv(os.path.join(root, field[f], machine[f][m], period[p]) + '.csv')
                    if datas is not None:
                        self.test_X_[f, m, p, ...] = datas[['变频器电网侧有功功率', '外界温度']].values.reshape(120, 2)
                        self.test_X0[f, m, p, ...] = datas[['风速', '风向']].values.reshape(120, 2)
                    self.test_W[f, p, ...] = weather[field[f]].query(f"时段 == '{period[p]}'")[['风速', '风向']].values

        self.test_X_ = np.moveaxis(self.test_X_, 1, 2)
        self.test_X0 = np.moveaxis(self.test_X0, 1, 2)

    def generate_indexes(self, val_times=1):

        '''
        {'风场1': {'春': None, '夏': None, '秋': None, '冬': None}, '风场2': {'春': None, '夏': None, '秋': None, '冬': None}}
        '''
        self.train_indexes = {field[f]: {season[s]: None for s in range(season_len)} for f in range(field_len)}
        '''
        {'风场1': 
        {0: array([], dtype=float64), 
        1: array([], dtype=float64), 
        2: array([], dtype=float64), 
        3: array([], dtype=float64), 
        4: array([], dtype=float64), 
        5: array([], dtype=float64),
        6: array([], dtype=float64), 
        7: array([], dtype=float64), 
        8: array([], dtype=float64), 
        9: array([], dtype=float64)},
        '风场2': {0: array([], dtype=float64), 1: array([], dtype=float64), 2: array([], dtype=float64), 3: array([], dtype=float64), 4: array([], dtype=float64), 5: array([], dtype=float64), 6: array([], dtype=float64), 7: array([], dtype=float64), 8: array([], dtype=float64), 9: array([], dtype=float64)}}
        '''
        self.val_indexes = {field[f]: {i: np.array([]) for i in range(val_times)} for f in range(field_len)}

        for f in range(field_len):
            for s in range(season_len):
                # ---------- update ----------
                # season_indexes = np.where((season[s] == self.S[f]) * self.n_indexes[f])[0]
                # 找出季节索引，春夏秋冬各自时段的索引
                # np.where(condition, [x, y]) 找到n维数组中特定数值的索引
                season_indexes = np.where(season[s] == self.S[f])[0]
                # ---------- update ----------
                '''
                #numpy.random.choice(a, size=None, replace=True, p=None)
                #从a(只要是ndarray都可以，但必须是一维的)中随机抽取数字，并组成指定大小(size)的数组
                #replace:True表示可以取相同数字，False表示不可以取相同数字
                #数组p：与数组a相对应，表示取数组a中每个元素的概率，默认为选取每个元素的概率相同。
                '''
                # val_times=10，选出train的数据集，每个季节减去20*10个时段
                train_indexes = np.random.choice(
                    season_indexes,
                    size=season_indexes.shape[0] - val_times * period_len // season_len,
                    replace=False
                )

                # 训练集的索引，每个季节各自4000多个时段
                self.train_indexes[field[f]][season[s]] = train_indexes
                '''
                setdiff1d(ar1, ar2, assume_unique=False)
                1.功能：找到2个数组中集合元素的差异。
                2.返回值：在ar1中但不在ar2中的已排序的唯一值。

                np.hstack():在水平方向上平铺


                '''
                # 验证集索引，总的索引去掉训练索引
                # 风场一的每份数据集，包括春夏秋冬，各数据集20个时段，共80个时段
                val_indexes = np.setdiff1d(season_indexes, train_indexes).reshape(val_times, period_len // season_len)
                for i in range(val_times):
                    self.val_indexes[field[f]][i] = np.hstack([self.val_indexes[field[f]][i], val_indexes[i]]).astype(
                        int)

    def get_indexes(self, f):
        indexes = np.array([])
        for s in range(season_len):
            indexes = np.hstack(
                [indexes, np.random.choice(self.train_indexes[field[f]][season[s]], size=20, replace=False)]).astype(
                int)
        return indexes

    @property
    def _merge_data(self):

        os.makedirs(self.root.encode('utf-8'), exist_ok=True)
        [os.makedirs(os.path.join(self.root, field[f]).encode('utf-8'), exist_ok=True) for f in range(field_len)]
        [shutil.copyfile(os.path.join('data','train', field[f], 'weather.csv').encode('utf-8'),
                         os.path.join(self.root, field[f], 'weather.csv').encode('utf-8')) for f in range(field_len)]

        for f in range(field_len):
            for m in range(machine_len):

                machine_dir = os.path.join('data','train', field[f], machine[f][m])

                machine_data_save_path = os.path.join(self.root, field[f], machine[f][m]) + '.csv'

                print(f'Merge {machine_dir} to {machine_data_save_path} ... \t', end='')

                # 用文件操作的方式将两年的数据合并, 用 pandas 合并太慢了
                with open(machine_data_save_path.encode('utf-8'), 'a', encoding='utf-8') as f1:
                    f1.write('time,变频器电网侧有功功率,外界温度,风向,风速\n')  # 列名
                    for data_file in os.listdir(machine_dir.encode('utf-8')):
                        if str(data_file, encoding = "utf-8") == '.ipynb_checkpoints':
                            shutil.rmtree(os.path.join(machine_dir,str(data_file, encoding = "utf-8")).encode('utf-8'))
                        else:
                            with open(os.path.join(machine_dir,str(data_file, encoding = "utf-8")).encode('utf-8'), 'r', encoding='utf-8') as f2:

                                f1.writelines(f2.readlines()[1:])  # [1:] -> 首行是列名，不写入

                # 根据 'time' 这一列合并数据
                df = pd.merge(
                    left=time_series[field[f]],
                    right=read_csv(machine_data_save_path),
                    how='left',
                    on=['time']
                )


                ff = open(machine_data_save_path.encode('utf-8'),mode='w', encoding="utf-8")
                #print(ff)
                xunlian = df.loc[:, ['time', '变频器电网侧有功功率', '外界温度', '风速', '风向']]
                xunlian
                xunlian["变频器电网侧有功功率"] = xunlian["变频器电网侧有功功率"].astype('float64')
                xunlian["外界温度"] = xunlian["外界温度"].astype('float64')
                xunlian["风速"] = xunlian["风速"].astype('float64')
                xunlian["风向"] = xunlian["风向"].astype('float64')

                xunlian.to_csv(ff,float_format='%.7f', index=False, encoding="utf-8")

                print('done!')

    # 检查生成的训练集是否存在
    @property
    def _check_file(self):  #
        for f in range(field_len):
            for m in range(machine_len):
                file = f'{os.path.join(self.root, field[f], machine[f][m])}.csv'
                if not os.path.exists(file.encode('utf-8')):
                    return True
            file = os.path.join(self.root, field[f], 'weather.csv')
            if not os.path.exists(file.encode('utf-8')):
                return True
        return False

    # 生成验证机结果
    def generate_dev(self):
        # 生成验证机结果
        print("生成验证集")
        pd.DataFrame(
            data={field[f]: self.val_indexes[field[f]][0] for f in range(field_len)},
            index=period
        ).to_csv('./data/val_indexes.csv', float_format='%.4f', encoding='utf-8')

        w_df = pd.DataFrame(
            index=np.arange(80 * 14),
            columns=['时段', '时刻', '风速', '风向']
        )
        w_df.loc[:, ['时段', '时刻']] = np.array(list(itertools.product(period, np.arange(-11, 2 + 1))))

        df = pd.DataFrame(
            data={'time': np.arange(1, 121) * 30},
            columns=['time', '变频器电网侧有功功率', '外界温度', '风速', '风向']
        )

        val_true_df = self.sample.copy()

        root = os.path.join('data', 'dev')
        os.makedirs(root, exist_ok=True)
        for f in range(field_len):
            os.makedirs(os.path.join(root, field[f]).encode('utf-8'), exist_ok=True)
            for m in tqdm(range(machine_len)):
                os.makedirs(os.path.join(root, field[f], machine[f][m]).encode('utf-8'), exist_ok=True)
                for p in range(period_len):
                    val_df = df.copy()
                    val_df.loc[:, ['变频器电网侧有功功率', '外界温度']] = self.X_[f, self.val_indexes[field[f]][0][p], m]
                    val_df.loc[:, ['风速', '风向']] = self.X0[f, self.val_indexes[field[f]][0][p], m]

                    ff = open((os.path.join(root, field[f], machine[f][m], period[p]) + '.csv').encode('utf-8'),mode='w', encoding="utf-8")
                    val_df.to_csv(ff, float_format='%.7f',
                                  index=False, encoding='utf-8')

                    val_true_df.loc[(val_true_df['风场'] == field[f]) & (val_true_df['风机'] == machine[f][m]) & (
                                val_true_df['时段'] == period[p]), ['风速', '风向']] = self.Y0[
                        f, self.val_indexes[field[f]][0][p], m]

            val_w_df = w_df.copy()
            val_w_df.loc[:, ['风速', '风向']] = self.W[f, self.val_indexes[field[f]][0]].reshape(80 * 14, 2)
            ff2 = open(os.path.join(root, field[f], 'weather.csv').encode('utf-8'),mode='w', encoding="utf-8")
            val_w_df.to_csv(ff2, float_format='%.3f', index=False,
                            encoding='utf-8')
        dev_true_path = os.path.join('data', 'dev_true.csv').encode('utf-8')
        ff3 = open(dev_true_path, mode='w', encoding="utf-8")
        val_true_df.fillna(0).to_csv(ff3, float_format='%.4f', index=False, encoding='utf-8')