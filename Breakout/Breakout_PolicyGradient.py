# -*- coding: utf-8 -*-
import numpy as np
import tensorflow as tf
import gym
from collections import deque
from skimage.transform import resize
from skimage.color import rgb2gray
import copy

env = gym.make('PongDeterministic-v3')

# 하이퍼 파라미터
LEARNING_RATE = 0.001
INPUT = env.observation_space.shape
OUTPUT = 3
DISCOUNT = 0.99
HEIGHT = 84
WIDTH = 84
HISTORY_SIZE = 4
EPSILON =0.01
MOMENTUM = 0.95
BATCH_SIZE = 256

model_path = 'save/pong-pg.ckpt'
def pre_proc(X):
    '''입력데이터 전처리.

    Args:
        X(np.array): 받아온 이미지를 그레이 스케일링 후 84X84로 크기변경
            그리고 정수값으로 저장하기위해(메모리 효율 높이기 위해) 255를 곱함

    Returns:
        np.array: 변경된 이미지
    '''
    # 바로 전 frame과 비교하여 max를 취함으로써 flickering을 제거
    # x = np.maximum(X, X1)
    # 그레이 스케일링과 리사이징을 하여 데이터 크기 수정
    x = np.uint8(resize(rgb2gray(X), (HEIGHT, WIDTH), mode='reflect') * 255)

    return x

def get_init_state(history, s):
    '''에피소드 시작 State를 초기화.

    Args:
        history(np.array): 5개의 프레임이 저장될 array
        s(list): 초기화된 이미지

    Note:
        history[:,:,:3]에 모두 초기화된 이미지(s)를 넣어줌
    '''
    for i in range(HISTORY_SIZE):
        history[:, :, i] = pre_proc(s)


def get_game_type(count, l, no_life_game, start_live):
    '''라이프가 있는 게임인지 판별

    Args:
        count(int): 에피소드 시작 후 첫 프레임인지 확인하기 위한 arg
        l(dict): 라이프 값들이 저장되어있는 dict ex) l['ale.lives']
        no_life_game(bool): 라이프가 있는 게임일 경우, bool 값을 반환해주기 위한 arg
        start_live(int): 라이프가 있는 경우 라이프값을 초기화 하기 위한 arg

    Returns:
        list:
            no_life_game(bool): 라이프가 없는 게임이면 True, 있으면 False
            start_live(int): 라이프가 있는 게임이면 초기화된 라이프
    '''
    if count == 1:
        start_live = l['ale.lives']
        # 시작 라이프가 0일 경우, 라이프 없는 게임
        if start_live == 0:
            no_life_game = True
        else:
            no_life_game = False
    return [no_life_game, start_live]


def get_terminal(start_live, l, reward, no_life_game, ter):
    '''목숨이 줄어들거나, negative reward를 받았을 때, terminal 처리

    Args:
        start_live(int): 라이프가 있는 게임일 경우, 현재 라이프 수
        l(dict): 다음 상태에서 라이프가 줄었는지 확인하기 위한 다음 frame의 라이프 info
        no_life_game(bool): 라이프가 없는 게임일 경우, negative reward를 받으면 terminal 처리를 해주기 위한 게임 타입
        ter(bool): terminal 처리를 저장할 arg

    Returns:
        list:
            ter(bool): terminal 상태
            start_live(int): 줄어든 라이프로 업데이트된 값
    '''
    if no_life_game:
        # 목숨이 없는 게임일 경우 Terminal 처리
        if reward < 0:
            ter = True
    else:
        # 목숨 있는 게임일 경우 Terminal 처리
        if start_live > l['ale.lives']:
            ter = True
            start_live = l['ale.lives']

    return [ter, start_live]

def discount_rewards(r):
    '''Discounted reward를 구하기 위한 함수

    Args:
         r(np.array): reward 값이 저장된 array

    Returns:
        discounted_r(np.array): Discounted 된 reward가 저장된 array
    '''
    discounted_r = np.zeros_like(r, dtype=np.float32)
    running_add = 0
    for t in reversed(range(len(r))):
        running_add = running_add * DISCOUNT + r[t]
        discounted_r[t] = running_add

    discounted_r = (discounted_r - discounted_r.mean()) / (discounted_r.std())

    return discounted_r


def train_episodic(PGagent, x, y, adv):
    '''에피소드당 학습을 하기위한 함수

    Args:
        PGagent(PolicyGradient): 학습될 네트워크
        x(np.array): State가 저장되어있는 array
        y(np.array): Action(one_hot)이 저장되어있는 array
        adv(np.array) : Discounted reward가 저장되어있는 array

    Returns:
        l(float): 네트워크에 의한 loss
    '''

    l, _ = PGagent.sess.run([PGagent.loss, PGagent.train], feed_dict={PGagent.X: np.float32(x/255.),
                                                                      PGagent.Y: y,
                                                                      PGagent.adv: adv})
    return l

def play_atari(PGagent):
    '''학습된 네트워크로 Play하기 위한 함수

    Args:
         PGagent(PolicyGradient): 학습된 네트워크
    '''
    print("Play Atari!")
    episode = 0
    while True:
        s = env.reset()
        history = np.zeros([84, 84, 5], dtype=np.uint8)
        done = False
        rall = 0
        episode += 1
        get_init_state(history, s)
        while not done:
            env.render()
            action_p = PGagent.sess.run(PGagent.a_pre,
                                        feed_dict={PGagent.X: np.reshape(np.float32(history[:,:,:4] / 255.), [-1, 84, 84, 4])})
            s1, reward, done, _ = env.step(np.argmax(action_p))
            history[:, :, 4] = pre_proc(s1)
            history[:, :, :4] = history[:, :, 1:]
            rall += reward
        print("[Episode {0:6f}] Reward: {1:4f} ".format(episode, rall))


class PolicyGradient:
    def __init__(self, sess, input_size, output_size):
        self.sess = sess
        self.input_size = input_size
        self.output_size = output_size
        self.height = HEIGHT
        self.width = WIDTH
        self.history_size = HISTORY_SIZE

        self.build_network()

    def build_network(self):
        self.X = tf.placeholder('float', [None, self.height, self.width, self.history_size])
        self.Y = tf.placeholder('float', [None, self.output_size])
        self.adv = tf.placeholder('float')

        f1 = tf.get_variable("f1", shape=[8, 8, 4, 32], initializer=tf.contrib.layers.xavier_initializer_conv2d())
        f2 = tf.get_variable("f2", shape=[4, 4, 32, 64], initializer=tf.contrib.layers.xavier_initializer_conv2d())
        f3 = tf.get_variable("f3", shape=[3, 3, 64, 64], initializer=tf.contrib.layers.xavier_initializer_conv2d())
        w1 = tf.get_variable("w1", shape=[7 * 7 * 64, 512], initializer=tf.contrib.layers.xavier_initializer())
        w2 = tf.get_variable("w2", shape=[512, OUTPUT], initializer=tf.contrib.layers.xavier_initializer())

        c1 = tf.nn.relu(tf.nn.conv2d(self.X, f1, strides=[1, 4, 4, 1], padding="VALID"))
        c2 = tf.nn.relu(tf.nn.conv2d(c1, f2, strides=[1, 2, 2, 1], padding="VALID"))
        c3 = tf.nn.relu(tf.nn.conv2d(c2, f3, strides=[1, 1, 1, 1], padding='VALID'))

        l1 = tf.reshape(c3, [-1, w1.get_shape().as_list()[0]])
        l2 = tf.nn.relu(tf.matmul(l1, w1))
        self.a_pre = tf.nn.softmax(tf.matmul(l2, w2))

        #self.pre = tf.matmul(l2,w2)
        #self.adv_Y = self.adv * (self.Y - self.a_pre) * LEARNING_RATE + self.a_pre
        #self.loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits = self.pre, labels=self.adv_Y))

        self.log_p = tf.log(tf.clip_by_value(tf.reduce_sum(self.a_pre * self.Y, axis=1), 1e-10, 1.))
        self.log_lik = -self.log_p * self.adv
        self.loss = tf.reduce_mean(self.log_lik)
        self.train = tf.train.AdamOptimizer(LEARNING_RATE).minimize(self.loss)

        self.saver = tf.train.Saver()

    def get_action(self, state, max_prob):
        action_p = self.sess.run(self.a_pre, feed_dict={self.X: np.reshape(np.float32(state/255.),[-1,84,84,4])})
        # 각 액션의 확률로 액션을 결정
        max_prob.append(np.max(action_p))
        action = np.random.choice(np.arange(self.output_size), p=action_p[0])

        return action

def main():
    with tf.Session(config = tf.ConfigProto(device_count ={'GPU' : 0})) as sess:
        PGagent = PolicyGradient(sess, INPUT, OUTPUT)

        sess.run(tf.global_variables_initializer())
        episode = 0
        recent_rlist = deque(maxlen=100)
        recent_rlist.append(0)
        no_life_game = False

        # 최근 100개의 점수가 195점 넘을 때까지 학습
        while np.mean(recent_rlist) <= 195:
            episode += 1

            state_memory = deque()
            action_memory = deque()
            reward_memory = deque()
            rewards = np.empty(0).reshape(0, 1)
            history = np.zeros([84, 84, 4], dtype=np.uint8)
            rall, count = 0, 0
            done = False
            ter = False
            start_lives = 0
            s = env.reset()
            max_prob = deque()
            get_init_state(history, s)

            while not done:
                # env.render()
                count += 1
                # 액션 선택
                action = PGagent.get_action(history, max_prob)

                # action을 one_hot으로 표현
                y = np.zeros(OUTPUT)
                y[action] = 1

                if action == 0:
                    real_a = 1
                elif action == 1:
                    real_a = 4
                else:
                    real_a = 5

                s1, reward, done, l = env.step(action + 1)

                ter = done
                rall += reward
                reward = np.clip(reward, -1, 1)
                # 라이프가 있는 게임인지 아닌지 판별
                no_life_game, start_lives = get_game_type(count, l, no_life_game, start_lives)

                # 라이프가 줄어들거나 negative 리워드를 받았을 때 terminal 처리를 해줌
                ter, start_lives = get_terminal(start_lives, l, reward, no_life_game, ter)

                # 목숨이 줄어 들었을때 -1 리워드를 줌(for Breakout)
                # if ter:
                #     reward = -1

                state_memory.append(np.copy(history))
                action_memory.append(y)
                reward_memory.append(reward)

                if reward != 0:
                    ep_reward = np.vstack(reward_memory)
                    discounted_rewards = discount_rewards(ep_reward)
                    rewards = np.vstack([rewards, discounted_rewards])
                    reward_memory = deque()

                # 새로운 프레임을 히스토리 마지막에 넣어줌
                history = np.append(history[:,:,1:],np.reshape(pre_proc(s1),[84,84,1]), axis=2)

                # 에피소드가 끝났을때 학습
                if done:
                    # print(np.stack(state_memory, axis=0).shape, np.stack(action_memory, axis =0).shape, rewards.shape)
                    l = train_episodic(PGagent, np.stack(state_memory, axis=0),
                                       np.stack(action_memory, axis =0), rewards)

            recent_rlist.append(rall)

            print("[Episode {0:6d}] Step:{4:6d} Reward: {1:4f} Loss: {2:5.5f} X e-5 Recent Reward: {3:4f} Max Prob: {5:5.5f}".
                  format(episode, rall, l*(1e+5), np.mean(recent_rlist), count, np.mean(max_prob)))

            if episode % 10 == 0:
                PGagent.saver.save(PGagent.sess, model_path, global_step= episode)
        play_atari(PGagent)


if __name__ == "__main__":
    main()





