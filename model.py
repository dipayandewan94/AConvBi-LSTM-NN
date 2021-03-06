import tensorflow as tf
from tensorflow_addons.activations import sparsemax
import keras
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dropout, Flatten, Embedding, LSTM, Bidirectional, multiply, Conv2D, GlobalMaxPooling1D, MaxPooling2D
from tensorflow.keras.layers import Dense, Lambda, dot, Activation, concatenate
from tensorflow.keras import regularizers
from tensorflow.keras import Model,Input
from tensorflow.keras import regularizers
from echoAI.Activation.TF_Keras.custom_activation import ELiSH,HardELiSH


class Attention(Layer):
    def __init__(self, local_shape, global_shape, method):
        super(Attention, self).__init__()
        self.__method = method

        self.__lcf_channel = local_shape[2]
        self.__lcf_H = local_shape[0]
        self.__lcf_W = local_shape[1]
        self.__glf_channel = global_shape

        self.__project = Dense(self.__lcf_channel, use_bias=False)
        self.__pc = Dense(1, use_bias=False)

    def __call__(self, inputs, *args, **kwargs):
        lcf = inputs[0]
        gbf = inputs[1]
        gbf_pj = self.__project(gbf) if self.__glf_channel != self.__lcf_channel else gbf   # (bs, c)
        lcf_rs = tf.reshape(lcf, [-1, self.__lcf_H * self.__lcf_W, self.__lcf_channel])     # (bs, h*w, c)
        if self.__method == 'dp':
            c = tf.squeeze(tf.matmul(lcf_rs, tf.expand_dims(gbf_pj, -1)), -1)
            # (bs, h*w, c) matmul (bs, c, 1) -> (bs, h*w, 1) -> (bs, h*w)
        elif self.__method == 'pc':
            add = tf.add(lcf_rs, tf.expand_dims(gbf_pj, -2))   # (bs, h*w, c)
            c = tf.squeeze(self.__pc(add), -1)  # (bs, h*w)
        else:
            c = None
            lcf_rs = None
            print('No such method', self.__method)
            exit(0)
        a = tf.nn.softmax(c, 1)     # (bs, h*w)
        ga = tf.squeeze(tf.matmul(tf.transpose(lcf_rs, [0, 2, 1]), tf.expand_dims(a, -1)), -1)
        # (bs, c, h*w) matmul (bs, h*w, 1) -> (bs, c)
        return ga, tf.reshape(a, [-1, self.__lcf_H, self.__lcf_W])

    
class ConvBlock(Layer):
    def __init__(self, filters, kernel_size, padding='same', pooling=False):
        super(ConvBlock, self).__init__()
        self.__filters = filters
        self.__ks = kernel_size
        self.__padding = padding
        self.__pooling = pooling

    def __call__(self, inputs, *args, **kwargs):
        _x = Conv2D(self.__filters, self.__ks, padding=self.__padding)(inputs)
        _x = BatchNormalization()(_x)
        _x = ELiSH()(_x)
        if self.__pooling:
            _x = MaxPooling2D()(_x)
        return _x


def attn(hidden_states,name='Attention_layer'):
    hidden_size = int(hidden_states.shape[2])
    # Inside dense layer
    #              hidden_states            dot               W            =>           score_first_part
    # (batch_size, time_steps, hidden_size) dot (hidden_size, hidden_size) => (batch_size, time_steps, hidden_size)
    # W is the trainable weight matrix of attention Luong's multiplicative style score
    score_first_part = Dense(hidden_size, use_bias=False)(hidden_states)
    #            score_first_part           dot        last_hidden_state     => attention_weights
    # (batch_size, time_steps, hidden_size) dot   (batch_size, hidden_size)  => (batch_size, time_steps)
    h_t = Lambda(lambda x: x[:, -1, :], output_shape=(hidden_size,))(hidden_states)
    score = dot([score_first_part, h_t], [2, 1])
    attention_weights = Activation('softmax')(score)
    # (batch_size, time_steps, hidden_size) dot (batch_size, time_steps) => (batch_size, hidden_size)
    context_vector = dot([hidden_states, attention_weights], [1, 1])
    pre_activation = concatenate([context_vector, h_t])
    attention_vector = Dense(128, use_bias=False, activation='tanh')(pre_activation)
    return attention_vector
        
def build_att_cnn_model():
    # VGG_NET 32       # [samples, W, H, colors]
    input_shape = (img_rows, img_cols, 3)
    
    inputs = Input(shape=input_shape)
               

    h_conv1_1 = Conv2D(filters=32, kernel_size=(3,3), name='conv1_1',kernel_regularizer=regularizers.l2(0.001))(inputs)
    h_conv1_1 = ELiSH()(h_conv1_1)
    h_conv1_2 = Conv2D(filters=32, kernel_size=(3,3), name='conv1_2',kernel_regularizer=regularizers.l2(0.001))(h_conv1_1)
    h_conv1_2 = ELiSH()(h_conv1_2)
    #h_conv1_3 = Conv2D(filters=32, kernel_size=(3,3), activation='relu', name='conv1_3')(h_conv1_2)
    #h_conv1_4 = Conv2D(filters=32, kernel_size=(3,3), activation='relu', name='conv1_4')(h_conv1_3)
    h_pool1 = MaxPooling2D(pool_size=(2,2), strides=(2,2), padding='same', name='max_pooling_1')(h_conv1_2)    # shape is (None, 16, 16, 32)
    h_pool1 = Dropout(0.25)(h_pool1)
    h_dense1 = Dense(32,activation = 'relu',kernel_regularizer=regularizers.l2(0.001),name='hid_dense_1')(h_pool1)
    h_squeez1 = tf.reshape(h_dense1,[tf.shape(h_dense1)[0],h_dense1.shape[1]*h_dense1.shape[2],h_dense1.shape[3]])
    #h_conv1_3 = Conv2D(filters=32, kernel_size=(14,1), name='conv1_2',kernel_regularizer=regularizers.l2(0.001))(h_pool1)
    #h_conv1_3 = ELiSH()(h_conv1_3)
    #h_squeez1 = tf.squeeze(h_conv1_3,axis=1)
    #print(h_squeez1.shape)
    h_attention1 = attn(h_squeez1,name='h_attention1')
    #print(h_attention1.shape)
    
               
    h_conv2_1 = Conv2D(filters=64, kernel_size=(3,3), name='conv2_1',kernel_regularizer=regularizers.l2(0.001))(h_pool1)
    h_conv2_1 = ELiSH()(h_conv2_1)
    h_conv2_2 = Conv2D(filters=64, kernel_size=(3,3), name='conv2_2',kernel_regularizer=regularizers.l2(0.001))(h_conv2_1)
    h_conv2_2 = ELiSH()(h_conv2_2)
    #h_conv2_3 = Conv2D(filters=64, kernel_size=(3,3), activation='relu', name='conv2_3')(h_conv2_2)
    h_pool2 = MaxPooling2D(pool_size=(2,2), strides=(2,2), padding='same', name='max_pooling_2')(h_conv2_2)    # shape is (None, 8, 8, 64)
    h_pool2 = Dropout(0.25)(h_pool2)
    h_dense2 = Dense(64,activation = 'relu',kernel_regularizer=regularizers.l2(0.001),name='hid_dense_2')(h_pool2)
    h_squeez2 = tf.reshape(h_dense2,[tf.shape(h_dense2)[0],h_dense2.shape[1]*h_dense2.shape[2],h_dense2.shape[3]])
    #h_conv2_3 = Conv2D(filters=32, kernel_size=(14,1), name='conv1_2',kernel_regularizer=regularizers.l2(0.001))(h_pool2)
    #h_conv2_3 = ELiSH()(h_conv2_3)
    #h_squeez2 = tf.squeeze(h_conv2_3,axis=1)
    #print(h_squeez2.shape)
    h_attention2 = attn(h_squeez2,name='h_attention2')
    #print(h_attention2.shape)
    
             
    #h_conv3_1 = Conv2D(filters=128, kernel_size=(3,3), activation='relu', name='conv3_1')(h_pool2)
    #h_conv3_2 = Conv2D(filters=128, kernel_size=(3,3), activation='relu', name='conv3_2')(h_conv3_1)
    #h_pool3 = MaxPooling2D(pool_size=(2,2), strides=(2,2), padding='same', name='max_pooling_3')(h_conv3_2)    # shape is (None, 4, 4, 128)
    #h_pool3 = Dropout(0.25)(h_pool3)
    #h_dense3 = Dense(256,activation = 'relu',kernel_regularizer=regularizers.l2(0.001),name='hid_dense_3')(h_pool3)
    #h_squeez3 = tf.reshape(h_dense3,[tf.shape(h_dense3)[0],h_dense3.shape[1]*h_dense3.shape[2],h_dense3.shape[3]])
    #h_conv3_3 = Conv2D(filters=32, kernel_size=(14,1), name='conv1_2',kernel_regularizer=regularizers.l2(0.001))(h_pool3)
    #h_conv3_3 = ELiSH()(h_conv3_3)
    #h_squeez3 = tf.squeeze(h_conv3_3,axis=1)
    #print(h_squeez3.shape)
    #h_attention3 = attn(h_squeez3,name='h_attention3')
    #print(h_attention3.shape)
    
           
    h_conv4_1 = Conv2D(filters=256, kernel_size=(3,3), activation='relu', name='conv4_1',kernel_regularizer=regularizers.l2(0.001))(h_pool2)
    h_conv4_1 = ELiSH()(h_conv4_1)
    h_pool4 = MaxPooling2D(pool_size=(2,2), strides=(2,2), padding='same', name='max_pooling_4')(h_conv4_1)    # shape is (None, 4, 4, 128)
    h_pool4 = Dropout(0.25)(h_pool4)
    h_dense4 = Dense(256,activation = 'relu',kernel_regularizer=regularizers.l2(0.001),name='hid_dense_4')(h_pool4)
    h_squeez4 = tf.reshape(h_dense4,[tf.shape(h_dense4)[0],h_dense4.shape[1]*h_dense4.shape[2],h_dense4.shape[3]])
    #h_conv4_3 = Conv2D(filters=32, kernel_size=(14,1), name='conv1_2',kernel_regularizer=regularizers.l2(0.001))(h_pool4)
    #h_conv4_3 = ELiSH()(h_conv4_3)
    #h_squeez4 = tf.squeeze(h_conv4_3,axis=1)
    #print(h_squeez4.shape)
    h_attention4 = attn(h_squeez4,name='h_attention4')
    #print(h_attention4.shape)
    
    flatten = Flatten()(h_pool4)
    attention = concatenate([h_attention1,h_attention2,h_attention4])
    merged = concatenate([attention,flatten])
    dense1 = Dense(256, activation='relu',kernel_regularizer=regularizers.l2(0.001))(merged)
    #dense1 = Dense(256, activation='relu',kernel_regularizer=regularizers.l2(0.001))(flatten)
    dense1 = Dropout(0.5)(dense1)
    dense2 = Dense(64, activation='relu',kernel_regularizer=regularizers.l2(0.001))(dense1)
    #outputs = Dense(num_classes, activation='softmax')(dense2)
    model = Model(inputs, dense2)
    #return dense2
    return model


def build_att_pool_cnn_model():
    # VGG_NET 32       # [samples, W, H, colors]
    input_shape = (img_rows, img_cols, 3)
    
    inputs = Input(shape=input_shape)
    
    _layer = ConvBlock(64, 3)(inputs)
    _layer = ConvBlock(128, 3)(_layer)
    c1 = ConvBlock(256, 3, pooling=False)(_layer)
    c1 = AveragePooling2D(pool_size=(2,2), strides=(2,2), padding='same', name='p1')(c1)
    c2 = ConvBlock(512, 3, pooling=False)(c1)
    c2 = AveragePooling2D(pool_size=(2,2), strides=(2,2), padding='same', name='p2')(c2)
    c3 = ConvBlock(512, 3, pooling=False)(c2)
    c3 = AveragePooling2D(pool_size=(2,2), strides=(2,2), padding='same', name='p3')(c3)
    _layer1 = ConvBlock(512, 3, pooling=True)(c3)
    _layer = ConvBlock(512, 3, pooling=True)(_layer1)
    _layer = Flatten()(_layer)
    _g = Dense(512, activation='relu')(_layer)
    att1_f, att1_map = Attention((16, 16, 256), 512, method='pc')([c1, _g])
    att2_f, att2_map = Attention((8, 8, 512), 512, method='pc')([c2, _g])
    att3_f, att3_map = Attention((4, 4, 512), 512, method='pc')([c3, _g])
    f_concat = tf.concat([att1_f, att2_f, att3_f], axis=1)
    #f_att = Flatten()(f_concat)
    #merged = concatenate([f_att,_layer])
    #_g = Dense(512, activation='relu')(merged)
    dense1 = Dense(256, activation='relu',kernel_regularizer=regularizers.l2(0.001))(f_concat)
    #dense1 = Dense(256, activation='relu',kernel_regularizer=regularizers.l2(0.001))(flatten)
    dense1 = Dropout(0.5)(dense1)
    dense2 = Dense(64, activation='relu',kernel_regularizer=regularizers.l2(0.001))(dense1)
    #outputs = Dense(num_classes, activation='softmax')(dense2)
    model = Model(inputs, dense2)
    #return dense2
    return model


def build_cnn_model():
    # VGG_NET 32       # [samples, W, H, colors]
    input_shape = (img_rows, img_cols, 3)
    
    inputs = Input(shape=input_shape)
                # layer_1   # 4个3*3*32

    h_conv1_1 = Conv2D(filters=32, kernel_size=(3,3), name='conv1_1',kernel_regularizer=regularizers.l2(0.001))(inputs)
    h_conv1_1 = ELiSH()(h_conv1_1)
    h_conv1_2 = Conv2D(filters=32, kernel_size=(3,3), name='conv1_2',kernel_regularizer=regularizers.l2(0.001))(h_conv1_1)
    h_conv1_2 = ELiSH()(h_conv1_2)
    #h_conv1_3 = Conv2D(filters=32, kernel_size=(3,3), activation='relu', name='conv1_3')(h_conv1_2)
    #h_conv1_4 = Conv2D(filters=32, kernel_size=(3,3), activation='relu', name='conv1_4')(h_conv1_3)
    h_pool1 = MaxPooling2D(pool_size=(2,2), strides=(2,2), padding='same', name='max_pooling_1')(h_conv1_2)    # shape is (None, 16, 16, 32)
    h_pool1 = Dropout(0.25)(h_pool1)
    
                # layer_2
    h_conv2_1 = Conv2D(filters=64, kernel_size=(3,3), name='conv2_1',kernel_regularizer=regularizers.l2(0.001))(h_pool1)
    h_conv2_1 = ELiSH()(h_conv2_1)
    h_conv2_2 = Conv2D(filters=64, kernel_size=(3,3), name='conv2_2',kernel_regularizer=regularizers.l2(0.001))(h_conv2_1)
    h_conv2_2 = ELiSH()(h_conv2_2)
    #h_conv2_3 = Conv2D(filters=64, kernel_size=(3,3), activation='relu', name='conv2_3')(h_conv2_2)
    h_pool2 = MaxPooling2D(pool_size=(2,2), strides=(2,2), padding='same', name='max_pooling_2')(h_conv2_2)    # shape is (None, 8, 8, 64)
    h_pool2 = Dropout(0.25)(h_pool2)
    
                # layer_3
    #h_conv3_1 = Conv2D(filters=128, kernel_size=(3,3), activation='relu', name='conv3_1')(h_pool2)
    #h_conv3_2 = Conv2D(filters=128, kernel_size=(3,3), activation='relu', name='conv3_2')(h_conv3_1)
    #h_pool3 = MaxPooling2D(pool_size=(2,2), strides=(2,2), padding='same', name='max_pooling_3')(h_conv3_2)    # shape is (None, 4, 4, 128)
    #h_pool3 = Dropout(0.25)(h_pool3)
    
                # layer_4
    h_conv4_1 = Conv2D(filters=256, kernel_size=(3,3), activation='relu', name='conv4_1',kernel_regularizer=regularizers.l2(0.001))(h_pool2)
    h_conv4_1 = ELiSH()(h_conv4_1)
    h_pool4 = MaxPooling2D(pool_size=(2,2), strides=(2,2), padding='same', name='max_pooling_4')(h_conv4_1)    # shape is (None, 4, 4, 128)
    h_pool4 = Dropout(0.25)(h_pool4)

    
    flatten = Flatten()(h_pool4)
    dense1 = Dense(256, activation='relu',kernel_regularizer=regularizers.l2(0.001))(flatten)
    dense1 = Dropout(0.5)(dense1)
    dense2 = Dense(64, activation='relu',kernel_regularizer=regularizers.l2(0.001))(dense1)
    #outputs = Dense(num_classes, activation='softmax')(dense2)
    model = Model(inputs, dense2)
    #return dense2
    return model


def make_bilstm_model():
  """Builds a bi-directional LSTM model."""
  inputs = Input(shape=(x_eeg_train.shape[1],), dtype='int64', name='eeg')
  #x = Lambda(rgb_to_grayscale, rgb_to_grayscale_output_shape)(input_tensor)
  #inputs = input_shape
  embedding_layer = Embedding(int(max_features+1),128)(inputs)
  lstm_layer1 = Bidirectional(LSTM(128,return_sequences=True,dropout=0.4, recurrent_dropout=0.2))(x)
  lstm_layer2 = Bidirectional(LSTM(64,dropout=0.3, recurrent_dropout=0.3))(lstm_layer1)
  dense_layer = Dense(64, activation='relu')(lstm_layer2)
  #outputs = Dense(num_classes, activation='softmax')(dense_layer)
  model = Model(inputs=inputs, outputs=dense_layer)
  return model
      

def make_atten_bilstm_model():
  """Builds a bi-directional LSTM model."""
  inputs = Input(shape=(x_stft_train.shape[1],), dtype='int64', name='stft')
  #x = Lambda(rgb_to_grayscale, rgb_to_grayscale_output_shape)(input_tensor)
  #inputs = input_shape
  embedding_layer = Embedding(int(max_features+1),128)(inputs)
  lstm_layer1 = Bidirectional(LSTM(64,return_sequences=True,dropout=0.2, recurrent_dropout=0.2,kernel_regularizer=regularizers.l2(0.001)))(embedding_layer)
  lstm_layer2 = Bidirectional(LSTM(64,return_sequences=True,dropout=0.2, recurrent_dropout=0.2,kernel_regularizer=regularizers.l2(0.001)))(lstm_layer1)
  attention_layer2 = attn(lstm_layer2)
  #flatten = GlobalMaxPooling1D()(attention_layer2)
  dense_layer = Dense(64, activation='relu',kernel_regularizer=regularizers.l2(0.001))(attention_layer2)
  #outputs = Dense(num_classes, activation='softmax')(dense_layer)
  #return dense_layer
  model = Model(inputs=inputs, outputs=dense_layer)
  return model

    
def make_atten1_bilstm_model():
  """Builds a bi-directional LSTM model."""
  inputs = Input(shape=(x_eeg_train.shape[1],50), name='eeg')
  #x = Lambda(rgb_to_grayscale, rgb_to_grayscale_output_shape)(input_tensor)
  #inputs = input_shape
  embedding_layer = Embedding(int(max_features_eeg+1),128)(inputs)
  lstm_layer1 = Bidirectional(LSTM(128,return_sequences=True,dropout=0.2, recurrent_dropout=0.2,kernel_regularizer=regularizers.l2(0.001)))(embedding_layer)
  lstm_layer2 = Bidirectional(LSTM(128,return_sequences=True,dropout=0.2, recurrent_dropout=0.2,kernel_regularizer=regularizers.l2(0.001)))(lstm_layer1)
  attention_layer2 = attn(lstm_layer2)
  #flatten = GlobalMaxPooling1D()(attention_layer2)
  dense_layer = Dense(64, activation='relu',kernel_regularizer=regularizers.l2(0.001))(attention_layer2)
  #outputs = Dense(num_classes, activation='softmax')(dense_layer)
  #return dense_layer
  model = Model(inputs=inputs, outputs=dense_layer)
  return model
  #return Model(inputs=input_tensor, outputs=outputs)
  
  
