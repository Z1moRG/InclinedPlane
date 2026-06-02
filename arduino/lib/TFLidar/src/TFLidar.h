

#ifndef TFLIDAR_H       // Guard to compile only once
#define TFLIDAR_H

#include <Arduino.h>    // Always include this. It's important.

// Buffer sizes
#define TFMP_FRAME_SIZE         9   // Size of data frame = 9 bytes
#define TFMP_REPLY_SIZE         8   // Longest command reply = 8 bytes
#define TFMP_COMMAND_MAX        8   // Longest command = 8 bytes

// Timeout Limits for various functions
#define TFMP_MAX_READS           20   // readData() sets SERIAL error
#define MAX_BYTES_BEFORE_HEADER  20   // getData() sets HEADER error
#define MAX_ATTEMPTS_TO_MEASURE  20

#define TFMP_DEFAULT_ADDRESS   0x10   // default I2C slave address
                                      // as hexidecimal integer
// System Error Status Condition
#define TFMP_READY           0  // no error
#define TFMP_SERIAL          1  // serial timeout
#define TFMP_HEADER          2  // no header found
#define TFMP_CHECKSUM        3  // checksum doesn't match
#define TFMP_TIMEOUT         4  // I2C timeout
#define TFMP_PASS            5  // reply from some system commands
#define TFMP_FAIL            6  //           "
#define TFMP_I2CREAD         7
#define TFMP_I2CWRITE        8
#define TFMP_I2CLENGTH       9
#define TFMP_WEAK           10  // Signal Strength ≤ 100             
#define TFMP_STRONG         11  // Signal Strength saturation
#define TFMP_FLOOD          12  // Ambient Light saturation
#define TFMP_MEASURE        13


#define    OBTAIN_FIRMWARE_VERSION    0x00010407   // returns 3 byte firmware version
#define    TRIGGER_DETECTION          0x00040400   // must have set frame rate to zero
                                                   // returns a 9 byte data frame
#define    SYSTEM_RESET               0x00020405   // returns a 1 byte pass/fail (0/1)
#define    RESTORE_FACTORY_SETTINGS   0x00100405   //           "
#define    SAVE_SETTINGS              0x00110405   // This must follow every command
                                                   // that modifies volatile parameters.
                                                   // Returns a 1 byte pass/fail (0/1)
                                                   
#define    SET_FRAME_RATE             0x00030606   // These commands each return
#define    SET_BAUD_RATE              0x00060808   // an echo of the command
#define    STANDARD_FORMAT_CM         0x01050505   //           "
#define    PIXHAWK_FORMAT             0x02050505   //           "
#define    STANDARD_FORMAT_MM         0x06050505   //           "
#define    ENABLE_OUTPUT              0x00070505   //           "
#define    DISABLE_OUTPUT             0x01070505   //           "
#define    SET_I2C_ADDRESS            0x100B0505   //           "

#define    SET_SERIAL_MODE            0x000A0500   // default is Serial (UART)
#define    SET_I2C_MODE               0x010A0500   // set device as I2C slave

#define    I2C_FORMAT_CM              0x01000500   // returns a 9 byte data frame
#define    I2C_FORMAT_MM              0x06000500   //           "

// *  *  *  *  *  *  *  Description of I/O Mode  *  *  *  *  *  *  * 
// Normally, device Pin 3 is either Serial transmit (TX) or I2C clock (SCL).
// When 'I/O Mode' is set other than 'Standard,' Pin 3 becomes a simple HI/LO
// (near/far) binary output.  Thereafter, only Pin 2, the Serial RX line, is
// functional, and only Serial data sent to the device is possible.
//#define    SET_IO_MODE_STANDARD     0x003B0900   // 'Standard' is default mode
//#define    SET_IO_MODE_HILO         0x013B0900   // I/O, near high and far low
//#define    SET_IO_MODE_LOHI         0x023B0900   // I/O, near low and far high
// *  *  *  This library does not support the I/O Mode interface  *  *  *

// Command Parameters
#define    BAUD_9600          0x002580   // UART serial baud rate
#define    BAUD_14400         0x003840   // expressed in hexidecimal
#define    BAUD_19200         0x004B00
#define    BAUD_56000         0x00DAC0
#define    BAUD_115200        0x01C200
#define    BAUD_460800        0x070800
#define    BAUD_921600        0x0E1000

#define    FRAME_0            0x0000    // internal measurement rate
#define    FRAME_1            0x0001    // expressed in hexidecimal
#define    FRAME_2            0x0002
#define    FRAME_5            0x0003
#define    FRAME_10           0x000A
#define    FRAME_20           0x0014
#define    FRAME_25           0x0019
#define    FRAME_50           0x0032
#define    FRAME_100          0x0064
#define    FRAME_125          0x007D
#define    FRAME_200          0x00C8
#define    FRAME_250          0x00FA
#define    FRAME_500          0x01F4
#define    FRAME_1000         0x03E8

// Object Class Definitions
class TFLidar
{
  public:
    TFLidar();
    ~TFLidar();

    uint8_t version[ 3];   // to save firmware version
    uint8_t status;        // to save library error status

    // Return T/F whether serial data available, set error status if not.
    bool begin( Stream *streamPtr);
    // Read device data and pass back three values
    bool getData( int16_t &dist, int16_t &flux, int16_t &temp);
    // Short version, passes back distance data only
    bool getData( int16_t &dist);
    // Build and send a command, and check response
    bool sendCommand( uint32_t cmnd, uint32_t param);
    
    //  For testing purposes: print frame or reply data and status
    //  as a string of HEX characters
    void printFrame();
    void printReply();    
    bool getResponse();

  private:
    Stream* pStream;      // pointer to the device serial stream
    // The data buffers are one byte longer than necessary
    // because we read one byte into the last position, then
    // shift the whole array left by one byte after each read.
    uint8_t frame[ TFMP_FRAME_SIZE + 1];
    uint8_t reply[ TFMP_REPLY_SIZE + 1];

    uint16_t chkSum;     // to calculate the check sum byte.

    // for testing - called by 'printFrame()' or 'printReply()'
    void printStatus();

};

#endif
